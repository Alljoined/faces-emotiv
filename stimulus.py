from psychopy import visual, core, event, gui, logging
from psychopy.monitors import Monitor
from psychopy.clock import Clock

import os
from scipy.io import loadmat
from PIL import Image
import random
import asyncio
from asyncio import Queue
import pathlib
import websockets # pip install websocket-client
import json
import ssl
import os
import time
from dotenv import load_dotenv # pip install python-dotenv
import h5py
import numpy as np
import pandas as pd

# Placeholder function for EEG setup and trigger recording
load_dotenv(override=True)
EMOTIV_ON = True
headset_info = {} # update this with the headset info

# Networking
ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
localhost_pem = pathlib.Path(__file__).with_name("cert.pem")
ssl_context.load_verify_locations(localhost_pem)

# Clock
experiment_start_time = time.time()
global_clock = Clock()
global_clock.reset()

# Face images
imgWidth = 875
imgHeight = 656

# Calculate aspect ratio
aspect_ratio = imgWidth / imgHeight

# Longer dimension size in degrees
longer_dim_size = 14  # degrees

# Determine sizes maintaining the aspect ratio
if imgWidth > imgHeight:
    size_deg = (longer_dim_size, longer_dim_size / aspect_ratio)
else:
    size_deg = (longer_dim_size * aspect_ratio, longer_dim_size)

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NpEncoder, self).default(obj)

async def send_message(message, websocket):
    attempt = 0
    retries = 3
    responses = []
    finished = False

    # if message["id"] == 5:
    #     import pdb
    #     pdb.set_trace()

    messageMethod = message["method"]
    while attempt < retries and not finished:
        try:
            message_json = json.dumps(message, cls=NpEncoder)
            await websocket.send(message_json)
            response = await websocket.recv()
            if message["id"] == 5:
                print(response)
            response = json.loads(response)
            responses.append(response)

            while "warning" in response and response["warning"]["code"] == 142:
                response = await websocket.recv()
                response = json.loads(response)
                responses.append(response)

            if messageMethod == "stopRecord":
                while True:
                    if "warning" in responses[-1]:
                        code = responses[-1]["warning"]["code"]
                        if code == 18:
                            break
                    response = await websocket.recv()
                    responses.append(json.loads(response))
                    # print("IN stopRecord" + response)
                    
            if messageMethod == "exportRecord":
                while True:
                    if "result" in responses[-1] and len(responses[-1]["result"]["success"]) > 0:
                        break
                    response = await websocket.recv()
                    responses.append(json.loads(response))

            finished = True
        except (websockets.exceptions.ConnectionClosedError, websockets.exceptions.WebSocketException) as e:
            attempt += 1
            print(f"Attempt {attempt}: Failed to communicate with WebSocket server - {e}")
            if attempt >= retries:
                print("Maximum retry attempts reached. Stopping.")
                return responses
            await asyncio.sleep(2)  # Wait a bit before retrying
    return responses

async def setup_eeg(websocket):
    # Initialize EEG, e.g., with Emotiv SDK
    # This function needs to be implemented based on your EEG SDK's documentation
    await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "requestAccess",
        "params": {
            "clientId": os.environ.get('CLIENT_ID'),
            "clientSecret": os.environ.get('CLIENT_SECRET'),
        }
    }, websocket)
    # give it access through launcher
    # refresh the device list
    await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "controlDevice",
        "params": {
            "command": "refresh"
        }
    }, websocket)
    # query the headsets
    response = await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "queryHeadsets"
    }, websocket)
    if len(response[-1]["result"]) == 0:
        print("No headsets found")
        exit(1)
    # connect to the headset
    headset = response[-1]["result"][0]["id"] # assuming the first headset, otherwise can manually specifiy
    with open('mapping.json', 'r') as file:
        mapping = json.load(file)
    await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "controlDevice",
        "params": {
            "command": "connect",
            "headset": headset,
            "mappings": mapping
        }
    }, websocket)
    response = await send_message({ # authorize the connection
        "id": 1,
        "jsonrpc": "2.0",
        "method": "authorize",
        "params": {
            "clientId": os.environ.get('CLIENT_ID'),
            "clientSecret": os.environ.get('CLIENT_SECRET'),
            "debit": 10
        }
    }, websocket)
    if "error" in response[-1]:
        error = response[-1]["error"]
        print(f"Error in authorizing {error}") # if it gets here, probably didn't set up env variables correctly
        exit(1)
    cortex_token = response[-1]["result"]["cortexToken"]
    await asyncio.sleep(0.2)
    response = await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "createSession",
        "params": {
            "cortexToken": cortex_token,
            "headset": headset,
            "status": "open"
        }
    }, websocket)
    session_id = response[-1]["result"]["id"]
    print("created session", session_id)
    await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "updateSession",
        "params": {
            "cortexToken": cortex_token,
            "session": session_id,
            "status": "active"
        }
    }, websocket)

    headset_info["headset"] = headset
    headset_info["cortex_token"] = cortex_token
    headset_info["session_id"] = session_id
    headset_info["record_id"] = None


async def export_and_delete_record(websocket, subj, session, block):
    # Save to output directory
    output_path = os.path.join("recordings", "subj_" + subj, "session_" + session, "block_" + str(block))
    if not os.path.exists(output_path):
        os.makedirs(output_path)
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_path)
    print("saving to directory:", output_path)

    response = await send_message({
        "id": 5,
        "jsonrpc": "2.0",
        "method": "exportRecord",
        "params": {
            "cortexToken": headset_info["cortex_token"],
            "folder": output_path,
            "format": "EDFPLUS",
            "recordIds": [headset_info["record_id"]],
            "streamTypes": [
                "EEG",
                "MOTION"
            ]
        }
    }, websocket)

    print("EXPORT RESULT")
    print(response)
    await asyncio.sleep(0.2)

    response = await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "deleteRecord",
        "params": {
            "cortexToken": headset_info["cortex_token"],
            "records": [headset_info["record_id"]]
        }
    }, websocket)

    print ("DELETE RECORD")
    print(response)


async def create_record(subj, session, block, websocket):
    print("creating record with block num", block)
    
    response = await send_message({
        "id": 69,
        "jsonrpc": "2.0",
        "method": "createRecord",
        "params": {
            "cortexToken": headset_info["cortex_token"],
            "session": headset_info["session_id"],
            "title": f"Subject {subj}, Session {session}, Block {block} Recording"
        }
    }, websocket)

    print("CREATE RECORD RESPONSE")
    print(response)
    record_id = response[-1]["result"]["record"]["uuid"]
    headset_info["record_id"] = record_id


async def stop_record(websocket):
    print("STOPPING RECORD")
    response = await send_message({
        "id": 15,
        "jsonrpc": "2.0",
        "method": "stopRecord",
        "params": {
            "cortexToken": headset_info["cortex_token"],
            "session": headset_info["session_id"]
        }
    }, websocket)


async def record_trigger(message, websocket, debug_mode=False):
    if debug_mode:
        logging.log(level=logging.DATA, msg=f"Trigger recorded: {message['label']} {message['value']}")
    else:
        await send_message({
            "id": 1,
            "jsonrpc": "2.0",
            "method": "injectMarker",
            "params": {
                "cortexToken": headset_info["cortex_token"],
                "session": headset_info["session_id"],
                "time": message['time'],
                "label": message['label'],
                "value": message['value']
            }
        }, websocket)


message_queue = Queue()
async def process_triggers(websocket):
    """Continuously receive and add messages to the queue."""
    while True:
        message = await message_queue.get()
        if message is None:
            break
        await record_trigger(message, websocket, False)
        message_queue.task_done()

def create_trials(n_images, num_blocks):
    trials = []

    image_list = list(range(1, n_images + 1))
    image_list = image_list * 40 # repeated images 40 times now
    random.shuffle(image_list)

    block_size = int(len(image_list) / num_blocks)
    for block in range(num_blocks):
        block_trials = image_list[block*block_size:(block+1)*block_size]
    
        for idx, trial in enumerate(block_trials):
            trials.append({
                'block': (block + 1), 
                'image': trial, 
                'end_of_block': (idx == block_size - 1)
            })

    return trials


def display_instructions(window, session_number):
    instruction_text = (
        f"Welcome to session {session_number} of the study.\n\n"
        "In this session, you will complete a perception task.\n"
        "This session consists of 20 experimental blocks.\n\n"
        "You will see sequences of images appearing on the screen.\n\n"
        "Sit comfortably, and keep your gaze focused on the red dot.\n\n"
        "When you are ready, press the space bar to start."
    )

    # Assuming a window width of 800 pixels, adjust this based on your actual window size
    # Use 80% of window width for text wrapping
    wrap_width = window.size[0] * 0.8

    message = visual.TextStim(window, text=instruction_text, pos=(0, 0), color=(1, 1, 1), height=40, wrapWidth=wrap_width)
    message.draw()
    window.flip()
    event.waitKeys(keyList=['space'])

def getImages(subj, session, n_images, num_blocks):
    pil_images = [Image.open(f"./stimulus/{index+1:04d}.png") for index in range(n_images)]
    indices =  [i for i in range(n_images)]

    return pil_images, indices

async def run_experiment(trials, window, websocket, subj, session, n_images, num_blocks):
    last_image = None
    # Initialize an empty list to hold the image numbers for the current block
    image_sequence = []
    display_message(window, "Preparing images...", block=False)
    images, indices = getImages(subj, session, n_images, num_blocks)

     # Display instructions
    display_instructions(window, session)
    print(subj, session, n_images, num_blocks)

    # Create a record for the session
    current_block = 1  # Initialize the current block counter
    start_index = (current_block - 1) * n_images
    end_index = start_index + n_images

    # Register the callback function for space presses
    # keyboard.on_press(on_space_press)

    if EMOTIV_ON:
        print("CREATE FIRST RECORD")
        await create_record(subj, session, current_block, websocket)

    for idx, trial in enumerate(trials):
        if trial['block'] != current_block:
            current_block = trial['block']

        image = images[trial['image'] - 1] # Recall that trial['images] 1-indexed and images is 0 indexed

        # Append current image number to the sequence list
        image_sequence.append(trial['image'])

        # Prepare the image
        image_stim = visual.ImageStim(win=window, image=image, pos=(0, 0), size=size_deg, units="degFlat")
        image_stim.draw()
        # fixation_dot = visual.Circle(window, size=(0.2,0.2), fillColor=(1, -1, -1), lineColor=(-1, -1, -1), opacity=0.5, edges=128, units="degFlat")
        # fixation_dot.draw()
        # Send trigger
        stim_time = time.time() * 1000
        print(f"{idx}: {trial['image']=}")
        await message_queue.put({'label': 'stim', 'value': trial['image'], 'time': stim_time})
        # Display the image for 500ms
        window.flip()
        await asyncio.sleep(0.5)

        # Rest screen with a fixation cross
        display_dot_with_jitter(window, 0.1, 0)

        keys = event.getKeys(keyList=["escape", "space"], timeStamped=global_clock)

        escape_pressed = False
        space_pressed = False
        space_time = None
        for key, timestamp in keys:
            if key == "escape":
                escape_pressed = True
            elif key == "space":
                space_pressed = True
                space_time = (experiment_start_time + timestamp) * 1000

        if escape_pressed: # Terminate experiment early if escape is pressed
            print("Experiment terminated early.")
            if EMOTIV_ON:
                display_message(window, "Processing recording...", block=False)
                await asyncio.sleep(1)
                await stop_record(websocket)
                await asyncio.sleep(1)
                display_message(window, "Saving recording...", block=False)
                await export_and_delete_record(websocket, subj, session, current_block)
            break

        # Check if end of block
        if trial['end_of_block']:
            if EMOTIV_ON:
                display_message(window, "Stopping recording...", block=False)
                await asyncio.sleep(1)
                await stop_record(websocket)
                await asyncio.sleep(1)
                display_message(window, "Saving recording...", block=False)
                await export_and_delete_record(websocket, subj, session, current_block)

            # Print the image sequence for the current block
            print(f"\nEnd of Block {trial['block']} Image Sequence: \n {', '.join(map(str, image_sequence))}")
            # Clear the list for the next block
            image_sequence = []

            # Display break message at the end of each block
            break_message = f"You've completed {trial['block']} blocks.\n\nTake a little break and press the space bar when you're ready to continue to the next block."
            display_message(window, break_message, block=True)

            # Create a new record for the next block
            if current_block < num_blocks:
                current_block += 1
                start_index = (current_block - 1) * n_images
                end_index = start_index + n_images
                print(f"\nBlock {current_block}, Start Index: {start_index}")
                print(f"Block {current_block}, End Index: {end_index}\n")

                if EMOTIV_ON:
                    print(f"CREATE {current_block} RECORD")
                    await create_record(subj, session, current_block, websocket)
                    print("Just created new record")

    # finally:
    #     if EMOTIV_ON:
    #         await stop_record(websocket)
    #         await teardown_eeg(websocket, subj, session)        

    # Stop the consumer task
    await message_queue.put(None)

def display_message(window, text, block=False):
    completion_message = visual.TextStim(window, text=text, pos=(0, 0), color=(1, 1, 1), height=40, wrapWidth=window.size[0] * 0.8)
    completion_message.draw()
    window.flip()
    if block:
        event.waitKeys(keyList=['space'])


def display_dot_with_jitter(window, base_time, jitter):
    rest_period = base_time + random.randint(0, int(jitter * 100)) / 100.0
    # Create a fixation dot with a black border and 50% opacity
    # fixation_dot = visual.Circle(window, size=(0.2,0.2), fillColor=(1, -1, -1), lineColor=(-1, -1, -1), opacity=0.5, edges=128, units="degFlat")
    # fixation_dot.draw()
    window.flip()
    core.wait(rest_period)


async def main():
    # Experiment setup
    # TODO: Fix order to be subject, session
    participant_info = {'Subject': '', 'Session': ''}
    dlg = gui.DlgFromDict(dictionary=participant_info, title='Experiment Info')

    if not dlg.OK:
        core.quit()

    # Monitor setup
    my_monitor = Monitor(name='Q27q-1L')
    my_monitor.setWidth(59.5)       # Monitor width in centimeters (physical size of screen)
    my_monitor.setDistance(60)    # Viewing distance in centimeters
    my_monitor.setSizePix((1920, 1080))  # Resolution in pixels
    my_monitor.save()

    # Default
    #window = visual.Window(fullscr=False, color=[0, 0, 0], units='pix')
    # window = visual.Window(screen=0, monitor="Q27q-1L", fullscr=False, size=(1920, 1080), color=(0, 0, 0), units='pix')

    # Asus external monitor   
    window = visual.Window(screen=0, monitor="Q27q-1L", fullscr=True, size=(1920, 1080), color=(0, 0, 0), units='pix')
    mouse = event.Mouse(win=window)
    mouse.setPos((1920, 1080))
    
    # Production Parameters
    n_images = 100  # Total number of unique images
    num_blocks = 20  # Division into number of blocks

    # Dev Parameters
    # n_images = 10  # Number of unique images per block (default 208)
    # num_blocks = 10

    trials = create_trials(n_images, num_blocks)

    # Setup EEG
    async with websockets.connect("wss://localhost:6868", ssl=ssl_context) as websocket:
        if EMOTIV_ON:
            display_message(window, "Connecting to headset...", block=False)
            await setup_eeg(websocket)
        
        # Run the experiment
        if EMOTIV_ON:
            experiment_task = asyncio.create_task(run_experiment(trials, window, websocket, participant_info['Subject'], participant_info['Session'], n_images, num_blocks))
            recording_task = asyncio.create_task(process_triggers(websocket))
            await asyncio.gather(experiment_task, recording_task) #return exceptions=True

        else: 
            await run_experiment(trials, window, websocket, participant_info['Subject'], participant_info['Session'], n_images, num_blocks)

        # Wind down and save results
        # Display completion message
        completion_text = "Congratulations! You have completed the experiment.\n\nPress the space bar to exit."
        display_message(window, completion_text, block=True)

        mouse.setVisible(True)

        window.close()
        core.quit()


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
    # asyncio.run(main())
