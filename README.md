# stimulus-eeg

Pyschopy requires python 3.8.

## Setup

1. Create a `.env` file based off of [.env.template](./.env.template). Go to [cortex dashboard](https://account.emotiv.com/my-account/cortex-apps/) to get an env key.
2. Create a file called `cert.pem` containing the contents from [this](https://github.com/Emotiv/cortex-example/blob/master/certificates/rootCA.pem)
3. Install all [requirements](./requirements.txt)
4. Download `coco_file_224_sub1_ses1.mat` and put it into a folder called `processed-stimulus`
5. Install the [emotive launcher](https://www.emotiv.com/products/emotiv-launcher#download)
6. Log into the emotiv launcher and set it up with the headset. This app will also act as a wss server
7. Run [`stimulus.py`](./stimulus.py)
8. On the first time running this script, use the emotiv launcher to accept access from the headset

## Imagery

You will need to run `download_coco.py` to download the images first. This will take 22gb.
After you will need to run `convert_224_stimuli_v2.py` to split the coco images into their respective files for ingestion in `stimulus.py`

## Tasks
- show faces for 1s
- randomize blocks of 100 images, 20 blocks