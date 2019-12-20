import argparse
import os
import re
import cv2
import time
import numpy as np
from torch.utils.data import DataLoader
from data_manipulation.utils import color_codes, find_file
from datasets import Cropping2DDataset
from models import  Unet2D


def parse_inputs():
    # I decided to separate this function, for easier acces to the command line parameters
    parser = argparse.ArgumentParser(description='Test different nets with 3D data.')

    # Mode selector
    parser.add_argument(
        '-d', '--mosaics-directory',
        dest='val_dir', default='/home/mariano/Dropbox/DEM_Annotations',
        help='Directory containing the mosaics'
    )
    parser.add_argument(
        '-e', '--epochs',
        dest='epochs',
        type=int,  default=10,
        help='Number of epochs'
    )
    parser.add_argument(
        '-p', '--patience',
        dest='patience',
        type=int, default=2,
        help='Patience for early stopping'
    )
    parser.add_argument(
        '-B', '--batch-size',
        dest='batch_size',
        type=int, default=32,
        help='Number of samples per batch'
    )
    parser.add_argument(
        '-t', '--patch-size',
        dest='patch_size',
        type=int, default=128,
        help='Patch size'
    )
    parser.add_argument(
        '-l', '--labels-tag',
        dest='lab_tag', default='top',
        help='Tag to be found on all the ground truth filenames'
    )

    options = vars(parser.parse_args())

    return options


def train_test_net(net_name, verbose=1):
    """

    :param net_name:
    :return:
    """
    # Init
    c = color_codes()
    options = parse_inputs()

    # Data loading (or preparation)
    d_path = options['val_dir']
    gt_names = sorted(list(filter(
        lambda x: not os.path.isdir(x) and re.search(options['lab_tag'], x),
        os.listdir(d_path)
    )))
    n_folds = len(gt_names)
    cases = [re.search(r'(\d+)', r).group() for r in gt_names]

    print(
            '%s[%s]%s Loading all mosaics and DEMs%s' %
            (c['c'], time.strftime("%H:%M:%S"), c['g'], c['nc'])
    )
    y = [
        (np.mean(cv2.imread(os.path.join(d_path, im)), axis=-1) < 2).astype(np.uint8)
        for im in gt_names
    ]
    dems = [
        cv2.imread(os.path.join(d_path, 'DEM{:}.jpg'.format(c_i)))
        for c_i in cases
    ]
    mosaics = [
        cv2.imread(os.path.join(d_path, 'mosaic{:}.jpg'.format(c_i)))
        for c_i in cases
    ]
    x = [
        np.moveaxis(
            np.concatenate([mosaic, np.expand_dims(dem[..., 0], -1)], -1),
            -1, 0
        )
        for mosaic, dem in zip(mosaics, dems)
    ]

    print(
        '%s[%s] %sStarting cross-validation (leave-one-mosaic-out)'
        ' - %d mosaics%s' % (
            c['c'], time.strftime("%H:%M:%S"), c['g'], n_folds, c['nc']
        )
    )
    for i, case in enumerate(cases):
        if verbose > 0:
            print(
                '%s[%s]%s Starting training for mosaic %s %s(%d/%d)%s' %
                (
                    c['c'], time.strftime("%H:%M:%S"),
                    c['g'], case,
                    c['c'], i + 1, len(cases), c['nc']
                )
            )

        test_y = y[i]
        test_x = x[i]

        train_y = y[:i] + y[i + 1:]
        train_x = x[:i] + x[i + 1:]

        val_split = 0.1
        batch_size = 32
        patch_size = (128, 128)
        overlap = (32, 32)
        num_workers = 1

        model_name = '{:}.mosaic{:}.mdl'.format(net_name, case)
        net = Unet2D()

        training_start = time.time()
        try:
            net.load_model(os.path.join(d_path, model_name))
        except IOError:

            # Dataloader creation
            if verbose > 0:
                n_params = sum(
                    p.numel() for p in net.parameters() if p.requires_grad
                )
                print(
                    '%sStarting training with a Unet 2D%s (%d parameters)' %
                    (c['c'], c['nc'], n_params)
                )

            if val_split > 0:
                n_samples = len(train_x)

                n_t_samples = int(n_samples * (1 - val_split))

                d_train = train_x[:n_t_samples]
                d_val = train_x[n_t_samples:]

                l_train = train_y[:n_t_samples]
                l_val = train_y[n_t_samples:]

                print('Training dataset (with validation)')
                train_dataset = Cropping2DDataset(
                    d_train, l_train, patch_size=patch_size, overlap=overlap
                )

                print('Validation dataset (with validation)')
                val_dataset = Cropping2DDataset(
                    d_val, l_val, patch_size=patch_size, overlap=overlap
                )
            else:
                print('Training dataset')
                train_dataset = Cropping2DDataset(
                    train_x, train_y, patch_size=patch_size, overlap=overlap
                )

                print('Validation dataset')
                val_dataset = Cropping2DDataset(
                    train_x, train_y, patch_size=patch_size, overlap=overlap
                )

            train_dataloader = DataLoader(
                train_dataset, batch_size, True, num_workers=num_workers
            )
            val_dataloader = DataLoader(
                val_dataset, batch_size, num_workers=num_workers
            )

            epochs = parse_inputs()['epochs']
            patience = parse_inputs()['patience']

            net.fit(
                train_dataloader,
                val_dataloader,
                epochs=epochs,
                patience=patience,
            )

            net.save_model(os.path.join(d_path, model_name))

        if verbose > 0:
            time_str = time.strftime(
                '%H hours %M minutes %S seconds',
                time.gmtime(time.time() - training_start)
            )
            print(
                '%sTraining finished%s (total time %s)\n' %
                (c['r'], c['nc'], time_str)
            )

            print(
                '%s[%s]%s Starting testing with mosaic %s %s(%d/%d)%s' %
                (
                    c['c'], time.strftime("%H:%M:%S"),
                    c['g'], case,
                    c['c'], i + 1, len(cases), c['nc']
                )
            )

        yi = net.test([test_x])[0]
        cv2.imwrite(
            os.path.join(d_path, 'pred_trees{:}.jpg'.format(case)),
            yi.astype(np.uint8)
        )


def main():
    # Init
    c = color_codes()

    print(
        '%s[%s] %s<Tree detection pipeline>%s' % (
            c['c'], time.strftime("%H:%M:%S"), c['y'], c['nc']
        )
    )

    ''' <Detection task> '''
    net_name = 'tree-detection.unet'

    train_test_net(net_name)


if __name__ == '__main__':
    main()