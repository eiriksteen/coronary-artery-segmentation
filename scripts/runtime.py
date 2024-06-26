import torch
import numpy as np
import torch.utils
import torch.utils.data
from tqdm import tqdm
from pathlib import Path
import nrrd
import torch.nn.functional as F
from torchvision.transforms import Resize
from transformers import SegformerForSemanticSegmentation, SegformerConfig
from mis.models import UNet2D, UNet2DNonLocal
from mis.settings import DEVICE, ASOCA_PATH
import time

def perform_runtime_analysis_unet(model_name, number_of_patients=3):
    
    scripts_dir = Path.cwd()
    model_dir = scripts_dir / f"{model_name}" / "epoch2" / "model"   # Change to correct epoch (best epoch)
    
    if "nonlocal" in model_name:
        if "concat" in model_name:
            model = UNet2DNonLocal(1, 1, skip_conn="concat").to(DEVICE)
        else:
            model = UNet2DNonLocal(1, 1, skip_conn="add").to(DEVICE)
    else:
        model = UNet2D(1, 1).to(DEVICE)
    model.load_state_dict(torch.load(model_dir, map_location="cpu"))

    normal_dir = ASOCA_PATH / "Normal" / "Testset_Normal"
    diseased_dir = ASOCA_PATH / "Diseased" / "Testset_Disease"      # Use this to test

    runtimes_dir = scripts_dir / "test_runtimes"
    runtimes_dir.mkdir(exist_ok=True)
    out_dir = runtimes_dir / f"{model_name}"
    out_dir.mkdir(exist_ok=True)
    
    loading_times = []
    data_preprocessing_times = []
    inference_times = []
    data_postprocessing_times = []
    total_times = []

    for i in range(10, 10 + number_of_patients):
        
        total_time_t0 = time.time()
        
        loading_time_t0 = time.time()
        img, _ = nrrd.read(diseased_dir / f"{i}.nrrd")
        loading_time_t1 = time.time()

        preds = np.zeros_like(img)
        
        data_preprocessing_times_slices = []
        inference_times_slices = []
        data_postprocessing_times_slices = []
        
        print(f"Predicting patient {i+1}...")
        for slice_idx in tqdm(range(img.shape[-1])):
            
            data_preprocessing_time_slice_t0 = time.time()
            ctca = img[:, :, slice_idx][None, :, :]
            ctca = ctca - ctca.min()
            ctca = ctca / np.abs(ctca).max()
            ctca = Resize((256, 256))(torch.Tensor(ctca)).to(DEVICE)
            data_preprocessing_time_slice_t1 = time.time()
            
            inference_time_slice_t0 = time.time()
            preds_nt = model(ctca[None,:,:,:])[-1]
            inference_time_slice_t1 = time.time()
            
            data_postprocessing_time_slice_t0 = time.time()
            preds_nu = torch.where(preds_nt>=0.5, 1.0, 0.0)
            preds_u = F.interpolate(preds_nu, scale_factor=2, mode="nearest")
            preds[:,:,slice_idx] = preds_u.detach().cpu().numpy()
            data_postprocessing_time_slice_t1 = time.time()
            
            data_preprocessing_times_slices.append(data_preprocessing_time_slice_t1 - data_preprocessing_time_slice_t0)
            inference_times_slices.append(inference_time_slice_t1 - inference_time_slice_t0)
            data_postprocessing_times_slices.append(data_postprocessing_time_slice_t1 - data_postprocessing_time_slice_t0)

        total_time_t1 = time.time()
        
        loading_times.append(loading_time_t1 - loading_time_t0)
        data_preprocessing_times.append(sum(data_preprocessing_times_slices))
        inference_times.append(sum(inference_times_slices))
        data_postprocessing_times.append(sum(data_postprocessing_times_slices))
        total_times.append(total_time_t1 - total_time_t0)
        
    loading_time = sum(loading_times) / len(loading_times)
    data_preprocessing_time = sum(data_preprocessing_times) / len(data_preprocessing_times)
    inference_time = sum(inference_times) / len(inference_times)
    data_postprocessing_time = sum(data_postprocessing_times) / len(data_postprocessing_times)
    total_time = sum(total_times) / len(total_times)
    
    percent_loading_time = round(loading_time / total_time * 100, 2)
    percent_data_preprocessing_time = round(data_preprocessing_time / total_time * 100, 2)
    percent_inference_time = round(inference_time / total_time * 100, 2)
    percent_data_postprocessing_time = round(data_postprocessing_time / total_time * 100, 2)

    print("Average times:")
    print(f"- Loading time: {loading_time} ({percent_loading_time}%)")
    print(f"- Data preprocessing time: {data_preprocessing_time} ({percent_data_preprocessing_time}%)")
    print(f"- Inference time: {inference_time} ({percent_inference_time}%)")
    print(f"- Data postprocessing time: {data_postprocessing_time} ({percent_data_postprocessing_time}%)")
    print(f"- Total time: {total_time}")

    with open(out_dir / "times.txt", "w") as f:
        f.write(f"Average times:\n")
        f.write(f"- Loading time: {loading_time} ({percent_loading_time}%)\n")
        f.write(f"- Data preprocessing time: {data_preprocessing_time} ({percent_data_preprocessing_time}%)\n")
        f.write(f"- Inference time: {inference_time} ({percent_inference_time}%)\n")
        f.write(f"- Data postprocessing time: {data_postprocessing_time} ({percent_data_postprocessing_time}%)\n")
        f.write(f"- Total time: {total_time}\n")
    

def perform_runtime_analysis_segformer(model_name, number_of_patients=3):
    """
    Perform runtime analysis on the Segformer model.

    Args:
        model_name (str): Name of the model to analyze.
        number_of_patients (int, optional): Number of patients used when analyzing. Defaults to 3.
    
    Returns:
        None: Prints inference times and saves them to a file
    """
    
    scripts_dir = Path.cwd()
    model_dir = scripts_dir / f"{model_name}" / "model"

    model = SegformerForSemanticSegmentation.from_pretrained("nvidia/mit-b0", num_labels=1).to(DEVICE)
    model.load_state_dict(torch.load(model_dir, map_location="cpu"))

    normal_dir = ASOCA_PATH / "Normal" / "Testset_Normal"
    diseased_dir = ASOCA_PATH / "Diseased" / "Testset_Disease"      # Use this to test

    runtimes_dir = scripts_dir / "test_runtimes"
    runtimes_dir.mkdir(exist_ok=True)
    out_dir = runtimes_dir / f"{model_name}"
    out_dir.mkdir(exist_ok=True)
    
    loading_times = []
    data_preprocessing_times = []
    inference_times = []
    data_postprocessing_times = []
    total_times = []

    for i in range(10, 10 + number_of_patients):
        
        total_time_t0 = time.time()
        
        loading_time_t0 = time.time()
        img, _ = nrrd.read(diseased_dir / f"{i}.nrrd")
        loading_time_t1 = time.time()

        preds = np.zeros_like(img)
        
        data_preprocessing_times_slices = []
        inference_times_slices = []
        data_postprocessing_times_slices = []
        
        print(f"Predicting patient {i+1}...")
        for slice_idx in tqdm(range(img.shape[-1])):
            
            data_preprocessing_time_slice_t0 = time.time()
            ctca = img[:, :, slice_idx][None, :, :]
            ctca = ctca - ctca.min()
            ctca = ctca / np.abs(ctca).max()
            ctca = Resize((256, 256))(torch.Tensor(ctca)).to(DEVICE)
            data_preprocessing_time_slice_t1 = time.time()
            
            inference_time_slice_t0 = time.time()
            preds_nt = model(ctca[None,:,:,:].repeat(1,3,1,1))[-1]
            inference_time_slice_t1 = time.time()
            
            data_postprocessing_time_slice_t0 = time.time()
            preds_nu = torch.where(preds_nt>=0.5, 1.0, 0.0)
            preds_u = F.interpolate(preds_nu, scale_factor=2, mode="nearest")
            data_postprocessing_time_slice_t1 = time.time()
            
            data_preprocessing_times_slices.append(data_preprocessing_time_slice_t1 - data_preprocessing_time_slice_t0)
            inference_times_slices.append(inference_time_slice_t1 - inference_time_slice_t0)
            data_postprocessing_times_slices.append(data_postprocessing_time_slice_t1 - data_postprocessing_time_slice_t0)

        total_time_t1 = time.time()
        
        loading_times.append(loading_time_t1 - loading_time_t0)
        data_preprocessing_times.append(sum(data_preprocessing_times_slices))
        inference_times.append(sum(inference_times_slices))
        data_postprocessing_times.append(sum(data_postprocessing_times_slices))
        total_times.append(total_time_t1 - total_time_t0)
        
    loading_time = sum(loading_times) / len(loading_times)
    data_preprocessing_time = sum(data_preprocessing_times) / len(data_preprocessing_times)
    inference_time = sum(inference_times) / len(inference_times)
    data_postprocessing_time = sum(data_postprocessing_times) / len(data_postprocessing_times)
    total_time = sum(total_times) / len(total_times)
    
    percent_loading_time = round(loading_time / total_time * 100, 2)
    percent_data_preprocessing_time = round(data_preprocessing_time / total_time * 100, 2)
    percent_inference_time = round(inference_time / total_time * 100, 2)
    percent_data_postprocessing_time = round(data_postprocessing_time / total_time * 100, 2)

    print("Average times:")
    print(f"- Loading time: {loading_time} ({percent_loading_time}%)")
    print(f"- Data preprocessing time: {data_preprocessing_time} ({percent_data_preprocessing_time}%)")
    print(f"- Inference time: {inference_time} ({percent_inference_time}%)")
    print(f"- Data postprocessing time: {data_postprocessing_time} ({percent_data_postprocessing_time}%)")
    print(f"- Total time: {total_time}")

    with open(out_dir / "times.txt", "w") as f:
        f.write(f"Average times:\n")
        f.write(f"- Loading time: {loading_time} ({percent_loading_time}%)\n")
        f.write(f"- Data preprocessing time: {data_preprocessing_time} ({percent_data_preprocessing_time}%)\n")
        f.write(f"- Inference time: {inference_time} ({percent_inference_time}%)\n")
        f.write(f"- Data postprocessing time: {data_postprocessing_time} ({percent_data_postprocessing_time}%)\n")
        f.write(f"- Total time: {total_time}\n")



if __name__ == "__main__":
    """
    Perform runtime analysis on the models.
    
    Args:
        None: Alter the model names and number of patients manually
    
    Returns:
        None: Prints inference times and saves them to a file
    """
    
    model_names = [
        # Input your model names here as strings
    ]
    number_of_patients = 2
    
    for model in model_names:
        if "unet2d" in model:
            perform_runtime_analysis_unet(model, number_of_patients)
        if "segformer" in model:
            perform_runtime_analysis_segformer(model, number_of_patients)
        else:
            ValueError("Model not recognized.")
    
    
