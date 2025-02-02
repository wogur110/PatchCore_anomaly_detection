from sklearn.random_projection import SparseRandomProjection
from sampling_methods.kcenter_greedy import kCenterGreedy
from torch.utils.data import Dataset, DataLoader
from sklearn.metrics import confusion_matrix
from scipy.ndimage import gaussian_filter
from sklearn.metrics import roc_auc_score
from torch.nn import functional as F
from torchvision import transforms
import pytorch_lightning as pl
from PIL import Image
import numpy as np
import argparse
import shutil
import faiss
import torch
import glob
import cv2
import os

from PIL import Image
from sklearn.metrics import roc_auc_score
from torch import nn
import pytorch_lightning as pl
from sklearn.metrics import confusion_matrix
import pickle
from sampling_methods.kcenter_greedy import kCenterGreedy
from sklearn.random_projection import SparseRandomProjection
from sklearn.neighbors import NearestNeighbors
from scipy.ndimage import gaussian_filter

from torchvision import models

from utils.common.utils import ifftc_torch, fftc_torch
from utils.common.visualize import visualize_TSNE
from math import floor

def distance_matrix(x, y=None, p=2):  # pairwise distance of vectors

    y = x if type(y) == type(None) else y

    n = x.size(0)
    m = y.size(0)
    d = x.size(1)

    x = x.unsqueeze(1).expand(n, m, d)
    y = y.unsqueeze(0).expand(n, m, d)

    dist = torch.pow(x - y, p).sum(2)

    return dist


class NN():

    def __init__(self, X=None, Y=None, p=2):
        self.p = p
        self.train(X, Y)

    def train(self, X, Y):
        self.train_pts = X
        self.train_label = Y

    def __call__(self, x):
        return self.predict(x)

    def predict(self, x):
        if type(self.train_pts) == type(None) or type(self.train_label) == type(None):
            name = self.__class__.__name__
            raise RuntimeError(f"{name} wasn't trained. Need to execute {name}.train() first")

        dist = distance_matrix(x, self.train_pts, self.p) ** (1 / self.p)
        labels = torch.argmin(dist, dim=1)
        return self.train_label[labels]

class KNN(NN):

    def __init__(self, X=None, Y=None, k=3, p=2):
        self.k = k
        super().__init__(X, Y, p)

    def train(self, X, Y):
        super().train(X, Y)
        if type(Y) != type(None):
            self.unique_labels = self.train_label.unique()

    def predict(self, x):


        # dist = distance_matrix(x, self.train_pts, self.p) ** (1 / self.p)
        dist = torch.cdist(x, self.train_pts, self.p)

        knn = dist.topk(self.k, largest=False)


        return knn

def copy_files(src, dst, ignores=[]):
    src_files = os.listdir(src)
    for file_name in src_files:
        ignore_check = [True for i in ignores if i in file_name]
        if ignore_check:
            continue
        full_file_name = os.path.join(src, file_name)
        if os.path.isfile(full_file_name):
            shutil.copy(full_file_name, os.path.join(dst,file_name))
        if os.path.isdir(full_file_name):
            os.makedirs(os.path.join(dst, file_name), exist_ok=True)
            copy_files(full_file_name, os.path.join(dst, file_name), ignores)

def prep_dirs(root):
    # make embeddings dir
    # embeddings_path = os.path.join(root, 'embeddings')
    if args.ADDFdataset :
        embeddings_path = os.path.join('./', 'embeddings', args.category, str(args.anomaly_class), args.img_type)
    else :
        embeddings_path = os.path.join('./', 'embeddings', args.category)
    os.makedirs(embeddings_path, exist_ok=True)
    # make sample dir
    sample_path = os.path.join(root, 'sample')
    os.makedirs(sample_path, exist_ok=True)
    # make source code record dir & copy
    source_code_save_path = os.path.join(root, 'src')
    os.makedirs(source_code_save_path, exist_ok=True)
    copy_files('./', source_code_save_path, ['.git','.vscode','__pycache__','logs','README','samples','LICENSE']) # copy source code
    return embeddings_path, sample_path, source_code_save_path

def embedding_concat(x, y):
    # from https://github.com/xiahaifeng1995/PaDiM-Anomaly-Detection-Localization-master
    B, C1, H1, W1 = x.size()
    _, C2, H2, W2 = y.size()
    s = int(H1 / H2)
    x = F.unfold(x, kernel_size=s, dilation=1, stride=s)
    x = x.view(B, C1, -1, H2, W2)
    z = torch.zeros(B, C1 + C2, x.size(2), H2, W2)
    for i in range(x.size(2)):
        z[:, :, i, :, :] = torch.cat((x[:, :, i, :, :], y), 1)
    z = z.view(B, -1, H2 * W2)
    z = F.fold(z, kernel_size=s, output_size=(H1, W1), stride=s)

    return z

def reshape_embedding(embedding):
    embedding_list = []
    for k in range(embedding.shape[0]):
        for i in range(embedding.shape[2]):
            for j in range(embedding.shape[3]):
                embedding_list.append(embedding[k, :, i, j])
    return embedding_list

#imagenet
mean_train = [0.485, 0.456, 0.406]
std_train = [0.229, 0.224, 0.225]

class ADDFDataset(Dataset):
    def __init__(self, root, transform, gt_transform, phase, crop_augmentation=False):
        if phase=='train':
            self.img_dirs = []
            if args.img_type == 'all' or args.img_type == 'edge' :
                self.img_dirs.append(os.path.join(root, 'edge_1f'))
            if args.img_type == 'all' or args.img_type == 'wafer' :
                self.img_dirs.append(os.path.join(root, 'wafer_1f'))
            if args.img_type == 'all' or args.img_type == 'xedge' :
                self.img_dirs.append(os.path.join(root, 'xedge_1f'))
        else:
            self.img_dirs = []
            if args.img_type == 'all' or args.img_type == 'edge' :
                self.img_dirs.append(os.path.join(root, 'edge_1f'))
            if args.img_type == 'all' or args.img_type == 'wafer' :
                self.img_dirs.append(os.path.join(root, 'wafer_1f'))
            if args.img_type == 'all' or args.img_type == 'xedge' :
                self.img_dirs.append(os.path.join(root, 'xedge_1f'))

            if args.anomaly_class == 1 :
                if args.img_type == 'all' or args.img_type == 'edge' :
                    self.img_dirs.append(os.path.join(root, 'edge_1fd1'))
                if args.img_type == 'all' or args.img_type == 'wafer' :
                    self.img_dirs.append(os.path.join(root, 'wafer_1fd1'))
                if args.img_type == 'all' or args.img_type == 'xedge' :
                    self.img_dirs.append(os.path.join(root, 'xedge_1fd1'))
            elif args.anomaly_class == 2 :
                if args.img_type == 'all' or args.img_type == 'edge' :
                    self.img_dirs.append(os.path.join(root, 'edge_1fd2'))
                if args.img_type == 'all' or args.img_type == 'wafer' :
                    self.img_dirs.append(os.path.join(root, 'wafer_1fd2'))
                if args.img_type == 'all' or args.img_type == 'xedge' :
                    self.img_dirs.append(os.path.join(root, 'xedge_1fd2'))
            elif args.anomaly_class == 3 :
                if args.img_type == 'all' or args.img_type == 'edge' :
                    self.img_dirs.append(os.path.join(root, 'edge_1fd3'))
                if args.img_type == 'all' or args.img_type == 'wafer' :
                    self.img_dirs.append(os.path.join(root, 'wafer_1fd3'))
                if args.img_type == 'all' or args.img_type == 'xedge' :
                    self.img_dirs.append(os.path.join(root, 'xedge_1fd3'))

        self.phase = phase
        self.transform = transform
        self.crop_augmentation = crop_augmentation
        # load dataset
        self.img_paths, self.labels, self.types = self.load_dataset() # self.labels => good : 0, anomaly : 1

    def load_dataset(self):

        img_tot_paths = []
        tot_labels = []
        tot_types = []

        path_offset = 0 if self.phase == 'train' else 1

        for img_dir in self.img_dirs :
            image_type = img_dir.split(os.path.sep)[-1]
            dataset_dirs = os.listdir(img_dir) # 'dataset00', 'dataset01', 'dataset02'

            for dataset_dir in dataset_dirs :
                if 'd1' in image_type or 'd2' in image_type or 'd3' in image_type :
                    img_paths = sorted(glob.glob(os.path.join(img_dir, dataset_dir) + "/*.png"))
                else :
                    img_paths = sorted(glob.glob(os.path.join(img_dir, dataset_dir) + "/*.png"))
                    img_paths = img_paths[path_offset::2]

                img_tot_paths.extend(img_paths)
                tot_types.extend([image_type]*len(img_paths))

                if 'd1' in image_type :
                    tot_labels.extend([1]*len(img_paths))
                elif 'd2' in image_type :
                    tot_labels.extend([2]*len(img_paths))
                elif 'd3' in image_type :
                    tot_labels.extend([3]*len(img_paths))
                else :
                    tot_labels.extend([0]*len(img_paths))

        return img_tot_paths, tot_labels, tot_types

    def __len__(self):
        if self.crop_augmentation :
            return len(self.img_paths) * 5
        return len(self.img_paths)

    def __getitem__(self, idx):
        if self.crop_augmentation :
            img_idx, offset_idx = floor(idx / 5), int(idx % 5)
        else :
            img_idx = idx

        img_path, label, img_type = self.img_paths[img_idx], self.labels[img_idx], self.types[img_idx]
        img = Image.open(img_path).convert('RGB')
        if self.crop_augmentation :
            img_tensor = self.transform(img)
            img = img_tensor[offset_idx]
        else :
            img = self.transform(img)

        # kspace_feature
        kspace_img = torch.abs(fftc_torch(img))
        kspace_img = kspace_img / kspace_img.max()
        normalize = transforms.Normalize(mean=mean_train, std=std_train)
        kspace_img = normalize(kspace_img)

        gt = torch.zeros([1, img.size()[-2], img.size()[-2]])

        assert img.size()[1:] == gt.size()[1:], "image.size != gt.size !!!"

        return img, kspace_img, gt, label, os.path.basename(img_path[:-4]), img_type

class MVTecDataset(Dataset):
    def __init__(self, root, transform, gt_transform, phase):
        if phase=='train':
            self.img_path = os.path.join(root, 'train')
        else:
            self.img_path = os.path.join(root, 'test')
            self.gt_path = os.path.join(root, 'ground_truth')
        self.transform = transform
        self.gt_transform = gt_transform
        # load dataset
        self.img_paths, self.gt_paths, self.labels, self.types = self.load_dataset() # self.labels => good : 0, anomaly : 1

    def load_dataset(self):

        img_tot_paths = []
        gt_tot_paths = []
        tot_labels = []
        tot_types = []

        defect_types = os.listdir(self.img_path)

        for defect_type in defect_types:
            if defect_type == 'good':
                img_paths = glob.glob(os.path.join(self.img_path, defect_type) + "/*.png")
                img_tot_paths.extend(img_paths)
                gt_tot_paths.extend([0]*len(img_paths))
                tot_labels.extend([0]*len(img_paths))
                tot_types.extend(['good']*len(img_paths))
            else:
                img_paths = glob.glob(os.path.join(self.img_path, defect_type) + "/*.png")
                gt_paths = glob.glob(os.path.join(self.gt_path, defect_type) + "/*.png")
                img_paths.sort()
                gt_paths.sort()
                img_tot_paths.extend(img_paths)
                gt_tot_paths.extend(gt_paths)
                tot_labels.extend([1]*len(img_paths))
                tot_types.extend([defect_type]*len(img_paths))

        assert len(img_tot_paths) == len(gt_tot_paths), "Something wrong with test and ground truth pair!"

        return img_tot_paths, gt_tot_paths, tot_labels, tot_types

    def __len__(self):
        return len(self.img_paths)

    def __getitem__(self, idx):
        img_path, gt, label, img_type = self.img_paths[idx], self.gt_paths[idx], self.labels[idx], self.types[idx]
        img = Image.open(img_path).convert('RGB')
        img = self.transform(img)
        if gt == 0:
            gt = torch.zeros([1, img.size()[-2], img.size()[-2]])
        else:
            gt = Image.open(gt)
            gt = self.gt_transform(gt)

        # kspace_feature
        kspace_img = torch.abs(fftc_torch(img))
        kspace_img = kspace_img / kspace_img.max()
        normalize = transforms.Normalize(mean=mean_train, std=std_train)
        kspace_img = normalize(kspace_img)

        assert img.size()[1:] == gt.size()[1:], "image.size != gt.size !!!"

        return img, kspace_img, gt, label, os.path.basename(img_path[:-4]), img_type


def cvt2heatmap(gray):
    heatmap = cv2.applyColorMap(np.uint8(gray), cv2.COLORMAP_JET)
    return heatmap

def heatmap_on_image(heatmap, image):
    if heatmap.shape != image.shape:
        heatmap = cv2.resize(heatmap, (image.shape[0], image.shape[1]))
    out = np.float32(heatmap)/255 + np.float32(image)/255
    out = out / np.max(out)
    return np.uint8(255 * out)

def min_max_norm(image):
    a_min, a_max = image.min(), image.max()
    return (image-a_min)/(a_max - a_min)


def cal_confusion_matrix(y_true, y_pred_no_thresh, thresh, img_path_list):
    pred_thresh = []
    false_n = []
    false_p = []
    for i in range(len(y_pred_no_thresh)):
        if y_pred_no_thresh[i] > thresh:
            pred_thresh.append(1)
            if y_true[i] == 0:
                false_p.append(img_path_list[i])
        else:
            pred_thresh.append(0)
            if y_true[i] == 1:
                false_n.append(img_path_list[i])

    cm = confusion_matrix(y_true, pred_thresh)
    print(cm)
    print('false positive')
    print(false_p)
    print('false negative')
    print(false_n)


class STPM(pl.LightningModule):
    def __init__(self, hparams):
        super(STPM, self).__init__()

        self.save_hyperparameters(hparams)

        self.init_features()
        def hook_t(module, input, output):
            self.features.append(output)

        #self.model = torch.hub.load('pytorch/vision:v0.9.0', 'wide_resnet50_2', pretrained=True)

        if args.model == 'R152' :
            self.model = models.resnet152()
            model_path = "/project/workSpace/aims-pvc/model/imagenet_pretrained/resnet152-b121ed2d.pth"
        elif args.model == 'R101' :
            self.model = models.resnet101()
            model_path = "/project/workSpace/aims-pvc/model/imagenet_pretrained/resnet101-5d3b4d8f.pth"
        elif args.model == 'R18' :
            self.model = models.resnet18()
            model_path = "/project/workSpace/aims-pvc/model/imagenet_pretrained/resnet18-f37072fd.pth"
        elif args.model == 'R34' :
            self.model = models.resnet34()
            model_path = "/project/workSpace/aims-pvc/model/imagenet_pretrained/resnet34-333f7ec4.pth"
        elif args.model == 'R50' :
            self.model = models.resnet50()
            model_path = "/project/workSpace/aims-pvc/model/imagenet_pretrained/resnet50-19c8e357.pth"
        elif args.model == 'WR50' :
            self.model = models.wide_resnet50_2()
            model_path = "/project/workSpace/aims-pvc/model/imagenet_pretrained/wide_resnet50_2-95faca4d.pth"

        self.model.load_state_dict(torch.load(model_path, map_location=self._device))

        for param in self.model.parameters():
            param.requires_grad = False

        if args.block_index == 1 :
            self.model.layer1[-1].register_forward_hook(hook_t)
            self.model.layer2[-1].register_forward_hook(hook_t)
        elif args.block_index == 2 :
            self.model.layer2[-1].register_forward_hook(hook_t)
            self.model.layer3[-1].register_forward_hook(hook_t)
        elif args.block_index == 3 :
            self.model.layer3[-1].register_forward_hook(hook_t)
            self.model.layer4[-1].register_forward_hook(hook_t)
        elif args.block_index == -1 :
            self.model.avgpool.register_forward_hook(hook_t)
        elif args.block_index == -2 :
            self.model.layer4[-1].register_forward_hook(hook_t)

        self.criterion = torch.nn.MSELoss(reduction='sum')

        self.init_results_list()

        self.data_crop_aug_transforms = transforms.Compose([
                        transforms.Resize((args.load_size, args.load_size), Image.ANTIALIAS),
                        transforms.CenterCrop((int)((args.load_size + args.input_size) / 2)),
                        transforms.FiveCrop(args.input_size),
                        transforms.Lambda(lambda crops: torch.stack([transforms.ToTensor()(crop) for crop in crops])),
                        transforms.Normalize(mean=mean_train,
                                            std=std_train)])
        self.data_transforms = transforms.Compose([
                        transforms.Resize((args.load_size, args.load_size), Image.ANTIALIAS),
                        transforms.ToTensor(),
                        transforms.CenterCrop(args.input_size),
                        transforms.Normalize(mean=mean_train,
                                            std=std_train)])
        self.gt_transforms = transforms.Compose([
                        transforms.Resize((args.load_size, args.load_size)),
                        transforms.ToTensor(),
                        transforms.CenterCrop(args.input_size)])

        self.inv_normalize = transforms.Normalize(mean=[-0.485/0.229, -0.456/0.224, -0.406/0.225], std=[1/0.229, 1/0.224, 1/0.225])

        self.viz_feature_list = []
        self.viz_class_idx_list = []

    def init_results_list(self):
        self.gt_list_px_lvl = []
        self.pred_list_px_lvl = []
        self.gt_list_img_lvl = []
        self.pred_list_img_lvl = []
        self.img_path_list = []
        self.img_type_list = []

    def init_features(self):
        self.features = []

    def forward(self, x_t):
        self.init_features()
        _ = self.model(x_t)
        return self.features

    def save_anomaly_map(self, anomaly_map, input_img, kspace_img, gt_img, file_name, x_type):
        if anomaly_map.shape != input_img.shape:
            anomaly_map = cv2.resize(anomaly_map, (input_img.shape[0], input_img.shape[1]))
        anomaly_map_norm = min_max_norm(anomaly_map)
        anomaly_map_norm_hm = cvt2heatmap(anomaly_map_norm*255)

        # anomaly map on image
        heatmap = cvt2heatmap(anomaly_map_norm*255)
        hm_on_img = heatmap_on_image(heatmap, input_img)

        # save images
        cv2.imwrite(os.path.join(self.sample_path, f'{x_type}_{file_name}.jpg'), input_img)
        cv2.imwrite(os.path.join(self.sample_path, f'{x_type}_{file_name}_amap.jpg'), anomaly_map_norm_hm)
        cv2.imwrite(os.path.join(self.sample_path, f'{x_type}_{file_name}_amap_on_img.jpg'), hm_on_img)
        cv2.imwrite(os.path.join(self.sample_path, f'{x_type}_{file_name}_gt.jpg'), gt_img)
        cv2.imwrite(os.path.join(self.sample_path, f'{x_type}_{file_name}_kspace.jpg'), kspace_img)

    def train_dataloader(self):
        if args.ADDFdataset :
            if args.crop_augmentation :
                image_datasets = ADDFDataset(root=os.path.join(args.dataset_path,args.category), transform=self.data_crop_aug_transforms, gt_transform=self.gt_transforms, phase='train', crop_augmentation=True)
            else :
                image_datasets = ADDFDataset(root=os.path.join(args.dataset_path,args.category), transform=self.data_transforms, gt_transform=self.gt_transforms, phase='train')
        else :
            image_datasets = MVTecDataset(root=os.path.join(args.dataset_path,args.category), transform=self.data_transforms, gt_transform=self.gt_transforms, phase='train')
        train_loader = DataLoader(image_datasets, batch_size=args.batch_size, shuffle=True, num_workers=0) #, pin_memory=True)
        print("length of train datasets :", len(image_datasets))
        return train_loader

    def test_dataloader(self):
        if args.ADDFdataset :
            test_datasets = ADDFDataset(root=os.path.join(args.dataset_path,args.category), transform=self.data_transforms, gt_transform=self.gt_transforms, phase='test')
        else :
            test_datasets = MVTecDataset(root=os.path.join(args.dataset_path,args.category), transform=self.data_transforms, gt_transform=self.gt_transforms, phase='test')
        test_loader = DataLoader(test_datasets, batch_size=1, shuffle=False, num_workers=0) #, pin_memory=True) # only work on batch_size=1, now.
        print("length of test datasets :", len(test_datasets))
        return test_loader

    def configure_optimizers(self):
        return None

    def on_train_start(self):
        self.model.eval() # to stop running_var move (maybe not critical)
        self.embedding_dir_path, self.sample_path, self.source_code_save_path = prep_dirs(self.logger.log_dir)
        self.embedding_list = []

    def on_test_start(self):
        self.index = faiss.read_index(os.path.join(self.embedding_dir_path,'index.faiss'))
        if torch.cuda.is_available():
            res = faiss.StandardGpuResources()
            self.index = faiss.index_cpu_to_gpu(res, 0 ,self.index)
        self.init_results_list()
        self.embedding_dir_path, self.sample_path, self.source_code_save_path = prep_dirs(self.logger.log_dir)

    def training_step(self, batch, batch_idx): # save locally aware patch features
        x, kspace_x, _, _, file_name, _ = batch
        
        features_img = self(x)
        features_kspace = self(kspace_x)

        if args.block_index == -1 or args.block_index == -2 :
            embedding_img = np.array(features_img[0].cpu())
            embedding_kspace = np.array(features_kspace[0].cpu())
        else : 
            embeddings_img = []
            embeddings_kspace = []
            m = torch.nn.AvgPool2d(3, 1, 1)
            for feature in features_img:                
                embeddings_img.append(m(feature))
            for feature in features_kspace:                
                embeddings_kspace.append(m(feature))
            embedding_img = np.array(embedding_concat(embeddings_img[0], embeddings_img[1]))
            embedding_kspace = np.array(embedding_concat(embeddings_kspace[0], embeddings_kspace[1]))
            
        if args.input_method == "kspace" :
            embedding_ = embedding_kspace
        elif args.input_method == "both" :
            embedding_ = np.concatenate((embedding_img, embedding_kspace), axis=1)
        elif args.input_method == "image" :
            embedding_ = embedding_img

        self.embedding_list.extend(reshape_embedding(embedding_))

    def training_epoch_end(self, outputs):
        total_embeddings = np.array(self.embedding_list)
        # Random projection
        self.randomprojector = SparseRandomProjection(n_components='auto', eps=0.9) # 'auto' => Johnson-Lindenstrauss lemma
        self.randomprojector.fit(total_embeddings)
        # Coreset Subsampling
        selector = kCenterGreedy(total_embeddings,0,0)
        selected_idx = selector.select_batch(model=self.randomprojector, already_selected=[], N=int(total_embeddings.shape[0]*args.coreset_sampling_ratio))
        self.embedding_coreset = total_embeddings[selected_idx]

        # whitening
        if args.whitening :
            self.embedding_mean, self.embedding_std = np.mean(self.embedding_coreset, axis=0), np.std(self.embedding_coreset, axis=0)
            self.embedding_coreset = (self.embedding_coreset - self.embedding_mean.reshape(1, -1)) / (args.whitening_offset + self.embedding_std.reshape(1, -1))

        if args.ADDFdataset and args.visualize:
            self.viz_feature_list += [self.embedding_coreset[idx] for idx in range(self.embedding_coreset.shape[0])]
            self.viz_class_idx_list += [0]*self.embedding_coreset.shape[0]

        print('initial embedding size : ', total_embeddings.shape)
        print('final embedding size : ', self.embedding_coreset.shape)
        #faiss
        self.index = faiss.IndexFlatL2(self.embedding_coreset.shape[1])
        self.index.add(self.embedding_coreset)
        faiss.write_index(self.index,  os.path.join(self.embedding_dir_path,'index.faiss'))

    def test_step(self, batch, batch_idx): # Nearest Neighbour Search
        x, kspace_x, gt, label, file_name, x_type = batch

        features_img = self(x)
        features_kspace = self(kspace_x)

        if args.block_index == -1 or args.block_index == -2 :
            embedding_img = np.array(features_img[0].cpu())
            embedding_kspace = np.array(features_kspace[0].cpu())
        else : 
            embeddings_img = []
            embeddings_kspace = []
            m = torch.nn.AvgPool2d(3, 1, 1)
            for feature in features_img:                
                embeddings_img.append(m(feature))
            for feature in features_kspace:                
                embeddings_kspace.append(m(feature))
            embedding_img = np.array(embedding_concat(embeddings_img[0], embeddings_img[1]))
            embedding_kspace = np.array(embedding_concat(embeddings_kspace[0], embeddings_kspace[1]))

        if args.input_method == "kspace" :
            embedding_ = embedding_kspace
        elif args.input_method == "both" :
            embedding_ = np.concatenate((embedding_img, embedding_kspace), axis=1)
        elif args.input_method == "image" :
            embedding_ = embedding_img

        embedding_test = np.array(reshape_embedding(embedding_))

        if args.whitening :
            embedding_test = (embedding_test - self.embedding_mean.reshape(1, -1)) / (args.whitening_offset + self.embedding_std.reshape(1, -1))

        if args.ADDFdataset and args.visualize:
            self.viz_feature_list += [embedding_test[idx] for idx in range(embedding_test.shape[0])]
            if label.cpu().numpy()[0] == 0 :
                viz_class_idx = 1
            else :
                if 'wafer' in x_type[0] :
                    viz_class_idx = 2
                elif 'edge' in x_type[0] and not 'xedge' in x_type[0]:
                    viz_class_idx = 3
                elif 'xedge' in x_type[0] :
                    viz_class_idx = 4
            self.viz_class_idx_list += [viz_class_idx]*embedding_test.shape[0]

        score_patches, feature_indices = self.index.search(embedding_test, k=1)
        score_patches = np.sqrt(score_patches)

        if args.block_index == 1:
            anomaly_map = score_patches[:,0].reshape((56,56))
        elif args.block_index == 2:
            anomaly_map = score_patches[:,0].reshape((28,28))
        elif args.block_index == 3:
            anomaly_map = score_patches[:,0].reshape((14,14))
        elif args.block_index == -1 :
            anomaly_map = score_patches[:,0].reshape((1,1))
        elif args.block_index == -2 :
            anomaly_map = score_patches[:,0].reshape((7,7))

        anomaly_max_idx = np.argmax(score_patches[:, 0])
        max_dist_score = score_patches[anomaly_max_idx, 0] # maximum distance score
        mean_dist_score = np.mean(score_patches[:, 0])
        anomaly_max_feature = embedding_test[anomaly_max_idx]
        nearest_patch_feature = self.index.reconstruct(feature_indices[anomaly_max_idx].item()) # nearest patch-feature from anomaly_max_feature
        _, b_nearest_patch_feature_indices = self.index.search(nearest_patch_feature.reshape(1, -1) , k=args.n_neighbors)

        neighbor_index = faiss.IndexFlatL2(self.embedding_coreset.shape[1])

        for i in range(b_nearest_patch_feature_indices.shape[1]) :
            neighbor_index.add(self.index.reconstruct(b_nearest_patch_feature_indices[0, i].item()).reshape(1, -1))

        neighbor_distances, _ = neighbor_index.search(anomaly_max_feature.reshape(1, -1), k=args.n_neighbors)
        neighbor_distances = np.sqrt(neighbor_distances)

        w = 1 - 1 / np.sum(np.exp(neighbor_distances - max_dist_score))

        score = w * max_dist_score # Image-level score
        #score = mean_dist_score # simplified Image-level score

        gt_np = gt.cpu().numpy()[0,0].astype(int)
        anomaly_map_resized = cv2.resize(anomaly_map, (args.input_size, args.input_size))
        anomaly_map_resized_blur = gaussian_filter(anomaly_map_resized, sigma=4)

        self.gt_list_px_lvl.extend(gt_np.ravel())
        self.pred_list_px_lvl.extend(anomaly_map_resized_blur.ravel())
        self.gt_list_img_lvl.append(label.cpu().numpy()[0])
        self.pred_list_img_lvl.append(score)
        self.img_path_list.extend(file_name)
        self.img_type_list.append(x_type[0])

        # save images
        x = self.inv_normalize(x).clip(0, 1)
        input_x = cv2.cvtColor(x.permute(0,2,3,1).cpu().numpy()[0]*255, cv2.COLOR_BGR2RGB)

        kspace_x = self.inv_normalize(kspace_x).clip(0, 1)
        kspace_x = cv2.cvtColor(kspace_x.permute(0,2,3,1).cpu().numpy()[0]*255, cv2.COLOR_BGR2RGB)
        self.save_anomaly_map(anomaly_map_resized_blur, input_x, kspace_x, gt_np*255, file_name[0], x_type[0])

    def test_epoch_end(self, outputs):
        if args.ADDFdataset :
            pixel_auc = 0
        else :
            print("Total pixel-level auc-roc score :")
            pixel_auc = roc_auc_score(self.gt_list_px_lvl, self.pred_list_px_lvl)
            print(pixel_auc)
        print("Total image-level auc-roc score :")

        img_auc = roc_auc_score(self.gt_list_img_lvl, self.pred_list_img_lvl)
        print(img_auc)
        print('test_epoch_end')
        values = {'pixel_auc': pixel_auc, 'img_auc': img_auc}

        if args.ADDFdataset :
            f = open("../all_train_result.txt", 'a')
            data = [args.category, str(args.anomaly_class), args.img_type, str(args.coreset_sampling_ratio), str(args.input_method), str(args.block_index), str(self.embedding_coreset.shape[0]), \
                str(args.crop_augmentation), str(args.whitening), str(args.whitening_offset), "{0:.4f}".format(img_auc)]
            data = ','.join(data) + '\n'
            f.write(data)
            f.close()

            if args.visualize :
                visualize_TSNE(self.viz_feature_list, self.viz_class_idx_list, "../visualize_TSNE.png")

        self.log_dict(values)
        # anomaly_list = []
        # normal_list = []
        # for i in range(len(self.gt_list_img_lvl)):
        #     if self.gt_list_img_lvl[i] == 1:
        #         anomaly_list.append(self.pred_list_img_lvl[i])
        #     else:
        #         normal_list.append(self.pred_list_img_lvl[i])

        # # thresholding
        # # cal_confusion_matrix(self.gt_list_img_lvl, self.pred_list_img_lvl, img_path_list = self.img_path_list, thresh = 0.00097)
        # # print()
        # with open(args.project_root_path + r'/results.txt', 'a') as f:
        #     f.write(args.category + ' : ' + str(values) + '\n')

def get_args():
    parser = argparse.ArgumentParser(description='ANOMALYDETECTION')
    parser.add_argument('--phase', choices=['train','test'], default='train')
    parser.add_argument('--dataset_path', default=r'../mvtec_dataset') # 'D:\Dataset\mvtec_anomaly_detection')#
    parser.add_argument('--ADDFdataset', default=False, action='store_true', help='Whether to use Anomaly Detection Defocused Dataset')
    parser.add_argument('--category', default='hazelnut') # iso/08F
    parser.add_argument('--anomaly_class', type=int, default=1, help='Class index which use as anomaly dataset, only use with ADDF dataset')
    parser.add_argument('--img_type', type=str, default='all', help='one of "all", "edge", "xedge", "wafer", only use with ADDF dataset')
    parser.add_argument('--num_epochs', default=1)
    parser.add_argument('--batch_size', default=32)
    parser.add_argument('--load_size', type=int, default=256) # 256
    parser.add_argument('--input_size', default=224)
    parser.add_argument('--coreset_sampling_ratio', type=float, default=1)
    parser.add_argument('--project_root_path', default=r'../anomaly_result') # 'D:\Project_Train_Results\mvtec_anomaly_detection\210624\test')
    parser.add_argument('--save_src_code', default=True)
    parser.add_argument('--save_anomaly_map', default=True)
    parser.add_argument('--n_neighbors', type=int, default=9)
    parser.add_argument('--model', choices=['WR50', 'R50', 'R34', 'R18', 'R101', 'R152'], default='WR50')
    parser.add_argument('--block_index', type=int, default=2) # 2 means block index [2, 3]
    parser.add_argument('--input_method', choices=['image','kspace','both'], default='image')
    parser.add_argument('--visualize', default=False, action='store_true', help='Whether to visualize t-SNE projection')
    parser.add_argument('--crop_augmentation', default=False, action='store_true', help='Whether to use crop augmentation')
    parser.add_argument('--whitening', default=False, action='store_true', help='Whether to use whitening features')
    parser.add_argument('--whitening_offset', type=float, default=0.001)

    parser.add_argument('--dwt_localize', default=False,  action='store_true', help='Whether to use dwt for anomaly localization')
    args = parser.parse_args()
    return args

if __name__ == '__main__':
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    args = get_args()
    if args.ADDFdataset :
        default_root_dir = os.path.join(args.project_root_path, args.category, str(args.anomaly_class), args.img_type)
    else :
        default_root_dir = os.path.join(args.project_root_path, args.category)
    trainer = pl.Trainer.from_argparse_args(args, default_root_dir=default_root_dir, max_epochs=args.num_epochs, gpus=1) #, check_val_every_n_epoch=args.val_freq,  num_sanity_val_steps=0) # ,fast_dev_run=True)
    model = STPM(hparams=args)
    if args.phase == 'train':
        trainer.fit(model)
        trainer.test(model)
    elif args.phase == 'test':
        trainer.test(model)

