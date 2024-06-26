import torch
import torch.nn as nn
import numpy as np
import argparse
import matplotlib.pyplot as plt
import json
import seaborn as sns
import torch.utils
import torch.utils.data
from sklearn.metrics import precision_recall_fscore_support, accuracy_score
from tqdm import tqdm
from pprint import pprint
from pathlib import Path
from torch.utils.data import Dataset, DataLoader
from mis.models import UNet2D, UNet2DNonLocal
from mis.datasets import ASOCADataset, BratsDataset
from mis.settings import DEVICE, ASOCA_PATH
from mis.loss import dice_loss, gdlv_loss, focal_loss

sns.set_style("darkgrid")
plt.rc("figure", figsize=(16, 8))
plt.rc("font", size=13)

torch.manual_seed(0)

def train(
        model: nn.Module,
        train_data: Dataset,
        validation_data: Dataset,
        args,
        out_dir: Path = Path("./training_results")
    ):

    print(f"lr={args.lr}\nnum_epochs={args.num_epochs}\nbatch_size={args.batch_size}")

    model = model.to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.99)
    train_dl = DataLoader(train_data, batch_size=args.batch_size, shuffle=True)
    validation_dl = DataLoader(validation_data, batch_size=args.batch_size)
    min_loss = float("inf")
    loss_fn = dice_loss if args.loss == "dice" else gdlv_loss if args.loss=="gdlv" else focal_loss
    train_losses, val_losses = [], []
    train_dices, val_dices = [], []

    for epoch in range(args.num_epochs):

        print(f"STARTING EPOCH {epoch+1}")
        train_loss, train_dice = 0, 0
        total_imgs, total_preds, total_masks = [], [], []
        model.train()

        pbar = tqdm(train_dl)
        for i, batch in enumerate(pbar):

            images = batch["image"].to(DEVICE)
            masks = batch["mask"].to(DEVICE)
            _, probs = model(images)
            loss = loss_fn(masks, probs)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            train_loss += loss.item()
            train_dice += 1 - dice_loss(masks, probs).item()
            
            if i % 10 == 0:
                pbar.set_description(f"(Loss, Dice) step {i} = ({train_loss / (i+1)}, {train_dice / (i+1)})")

        print("RUNNING VALIDATION")
        model.eval()
        val_loss, val_dice  = 0, 0
        with torch.no_grad():
            pbar = tqdm(validation_dl)
            for i, batch in enumerate(pbar):

                images = batch["image"].to(DEVICE)
                masks = batch["mask"].to(DEVICE)
                _, probs = model(images)
                loss = loss_fn(masks, probs)
                val_loss += loss.item()
                val_dice += 1 - dice_loss(masks, probs).item()

                preds = torch.where(probs >= 0.5, 1.0, 0.0) if args.thresh else probs

                total_imgs += images.detach().cpu().tolist()
                total_preds += preds.detach().cpu().tolist()
                total_masks += masks.detach().cpu().tolist()

                if i % 10 == 0:
                    pbar.set_description(f"(Loss, Dice) step {i} = ({val_loss / (i+1)}, {val_dice / (i+1)})")

        total_masks_np = np.asarray(total_masks)
        total_preds_np = np.asarray(total_preds)

        if args.thresh:
            a = accuracy_score(total_masks_np.flatten(), total_preds_np.flatten())
            p, r, f, s = precision_recall_fscore_support(total_masks_np.flatten(), total_preds_np.flatten())

        train_loss = train_loss / len(train_dl)
        val_loss = val_loss / len(validation_dl)
        train_dice = train_dice / len(train_dl)
        val_dice = val_dice / len(validation_dl)

        metrics = {
            "val_loss": val_loss,
            "train_loss": train_loss,
            "val_dice": val_dice,
            "train_dice": train_dice,
        }

        if args.thresh:
            a = accuracy_score(total_masks_np.flatten(), total_preds_np.flatten())
            p, r, f, s = precision_recall_fscore_support(total_masks_np.flatten(), total_preds_np.flatten())
            metrics["accuracy"] = a
            metrics["precision"] = p.tolist()
            metrics["recall"] = r.tolist()
            metrics["f1"] = f.tolist()
            metrics["support"] = s.tolist()

        train_losses.append(train_loss)
        val_losses.append(val_loss)
        train_dices.append(train_dice)
        val_dices.append(val_dice)

        if val_loss < min_loss:
            print("New min loss, saving model...")
            min_loss = val_loss

            epoch_dir = out_dir / f"epoch{epoch+1}"
            epoch_dir.mkdir(exist_ok=True)

            torch.save(model.state_dict(), epoch_dir / "model")
  
            with open(epoch_dir / "metrics.json", "w") as f:
                json.dump(metrics, f)

            total_imgs_np = np.asarray(total_imgs)
            rand_idx = np.random.choice(len(total_preds), 50, replace=False)

            for idx in rand_idx:
                _, ax = plt.subplots(ncols=3)
                img = total_imgs_np[idx]
                mask = total_masks_np[idx]
                pred = total_preds_np[idx]

                ax[0].imshow(img.squeeze())
                ax[0].set_title("Image")
                ax[1].imshow(mask.squeeze())
                ax[1].set_title("Ground Truth")
                ax[2].imshow(pred.squeeze())
                ax[2].set_title("Prediction")

                plt.savefig(epoch_dir / f"pred{idx}")
                plt.close()

        pprint(metrics)

    plt.title("Loss Per Epoch")
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.plot(train_losses)
    plt.plot(val_losses)
    plt.legend(["Train Loss", "Validation Loss"])
    plt.savefig(out_dir / "loss.png")
    plt.close()

    plt.title("Dice Per Epoch")
    plt.xlabel("Epoch")
    plt.ylabel("Dice")
    plt.plot(train_dices)
    plt.plot(val_dices)
    plt.legend(["Train Dice", "Validation Dice"])
    plt.savefig(out_dir / "dice.png")
    plt.close()


if __name__ == "__main__":
    """
    Trains a 2D UNet model on the ASOCA dataset or the BraTS dataset.
 
    Args:
        --lr: Learning rate for the optimizer
        --batch_size: Batch size for training
        --num_epochs: Number of epochs to train for
        --loss: Loss function to use. Must be one of "dice", "focal", or "gdlv"
        --dataset: Dataset to use. Must be one of "asoca" or "brats"
        --skip_conn: Skip connection type to use. Must be one of "concat" or "add"
        --split_strat: Split strategy to use. Must be one of "patientwise" or "random"
        --merge_test_val: Whether to merge the test and validation sets
        --thresh: Whether to threshold the predictions
 
    Returns:
        None: Stores the model and metrics in a directory
    """

    parser = argparse.ArgumentParser()

    parser.add_argument("--lr", default=1e-04, type=float)
    parser.add_argument("--batch_size", default=8, type=int)
    parser.add_argument("--num_epochs", default=3, type=int)
    parser.add_argument("--loss", default="dice", type=str)
    parser.add_argument("--dataset", default="asoca", type=str)
    parser.add_argument("--skip_conn", default="concat", type=str)
    parser.add_argument("--split_strat", default="patientwise", type=str)
    parser.add_argument("--merge_test_val", action=argparse.BooleanOptionalAction)
    parser.add_argument("--non_local", action=argparse.BooleanOptionalAction)
    parser.add_argument("--thresh", action=argparse.BooleanOptionalAction)

    args = parser.parse_args()

    losses = ["dice", "focal", "gdlv"]
    if args.loss not in losses:
        raise ValueError(f"Loss must be in {losses}")
    
    dsets = ["asoca", "brats"]
    if args.dataset not in dsets:
        raise ValueError(f"Dset must be in {dsets}")

    if args.dataset == "asoca":

        if args.split_strat == "patientwise":
            train_data = ASOCADataset(
                size=256,
                split="train",
                merge_test_validation=args.merge_test_val,
                two_dim=True,
                to_torch=True,
                norm=True,
                data_dir=ASOCA_PATH,
                thresh=args.thresh,
                split_strat=args.split_strat
            )
            val_data = ASOCADataset(
                size=256,
                split="validation",
                merge_test_validation=args.merge_test_val,
                two_dim=True,
                to_torch=True,
                norm=True,
                data_dir=ASOCA_PATH,
                thresh=args.thresh,
                split_strat=args.split_strat
            )

        else:
            data = ASOCADataset(
                size=256,
                two_dim=True,
                to_torch=True,
                norm=True,
                data_dir=ASOCA_PATH,
                thresh=args.thresh,
                split_strat=args.split_strat
            )

            train_data, val_data = torch.utils.data.random_split(data, [0.8, 0.2])
    else:
        data = BratsDataset(
            "train"
        )

        train_data, val_data = torch.utils.data.random_split(data, [0.8, 0.2])

    print(f"RUNNING WITH {len(train_data)} TRAIN SAMPLES AND {len(val_data)} VALID SAMPLES")

    out_dir = Path(f"unet2d{'_nonlocal' if args.non_local else ''}_results_{args.loss}_{args.skip_conn}{'_t' if args.thresh else ''}_{args.split_strat}{'_mtv' if args.merge_test_val else ''}")
    out_dir.mkdir(exist_ok=True)

    model = UNet2DNonLocal(1, 1, skip_conn=args.skip_conn) if args.non_local else UNet2D(1, 1, args.skip_conn)

    try:
        model.load_state_dict(torch.load(out_dir / "model"))
        print(f"Found model at {out_dir / 'model'}, resuming training")
    except FileNotFoundError:
        print(f"No model found at {out_dir / 'model'}, training from scratch")

    train(
        model,
        train_data,
        val_data,
        args,
        out_dir=out_dir
    )
