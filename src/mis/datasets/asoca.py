import torch
import nrrd
import numpy as np
from torch.utils.data import Dataset
from torchvision.transforms import Resize
from pathlib import Path
from tqdm import tqdm

class ASOCADataset(Dataset):

    def __init__(
            self,
            size: int = 256,
            two_dim: bool = True,
            to_torch: bool = True,
            norm: bool = True,
            data_dir: Path = Path("/cluster/projects/vc/data/mic/open/Heart/ASOCA"),
        ):
        super().__init__()

        self.size = size
        self.two_dim = two_dim
        self.to_torch = to_torch
        self.norm = norm
        self.data_dir = data_dir
        self.n_path = data_dir / "Normal"
        self.d_path = data_dir / "Diseased"
        self.num_slices, self.num_normal, self.num_diseased = self.get_num_slices()
        self.slice_cumsums = np.asarray(self.num_slices).cumsum()

    def __len__(self):
        return sum(self.num_slices)

    def __getitem__(self, index):
        patient_idx = np.argwhere(self.slice_cumsums>index)[0,0]
        slice_idx = index % self.num_slices[patient_idx]

        if patient_idx < self.num_normal:
            ctca_path = next(iter((self.n_path/"CTCA").glob(f"Normal_{patient_idx+1}*")))
            anno_path = next(iter((self.n_path/"Annotations").glob(f"Normal_{patient_idx+1}*")))
        else:
            ctca_path = next(iter((self.d_path/"CTCA").glob(f"Diseased_{patient_idx%self.num_normal+1}*")))
            anno_path = next(iter((self.d_path/"Annotations").glob(f"Diseased_{patient_idx%self.num_normal+1}*")))

        ctca, _ = nrrd.read(ctca_path)
        ctca = ctca[:,:,slice_idx][None, :, :]
        anno, _ = nrrd.read(anno_path)

        if self.norm:
            ctca = ctca - ctca.min()
            ctca = ctca / np.abs(ctca).max()

        if self.to_torch:
            ctca = Resize((self.size, self.size))(torch.Tensor(ctca))
            anno = Resize((self.size, self.size))(torch.Tensor(anno))

        return {
            "image": ctca,
            "mask": anno
        }

    def get_num_slices(self):

        num_slices = []
        num_normal = len(list((self.n_path / "CTCA").glob("Normal*")))
        num_diseased = len(list((self.d_path / "CTCA").glob("Diseased*")))
        
        for i in range(num_normal):
            data, _ = nrrd.read(self.n_path / "CTCA" / f"Normal_{i+1}.nrrd")
            num_slices.append(data.shape[-1])

        for i in range(num_diseased):
            data, _ = nrrd.read(self.d_path / "CTCA" / f"Diseased_{i+1}.nrrd")
            num_slices.append(data.shape[-1])

        return num_slices, num_normal, num_diseased