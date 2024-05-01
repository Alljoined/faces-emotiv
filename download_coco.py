from huggingface_hub import hf_hub_download 

hf_hub_download(repo_id="pscotti/mindeyev2", filename="stimulus/coco_images_224_float16.hdf5", repo_type="dataset", cache_dir="./stimulus", resume_download=True)
