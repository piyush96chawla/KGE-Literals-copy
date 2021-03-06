import sys
sys.path.append('.')

from kga.models.base import *
from kga.metrics import *
from kga.util import *
import numpy as np
import torch.optim
import argparse
import os
from time import time
from sklearn.utils import shuffle as skshuffle


parser = argparse.ArgumentParser(
    description='Train baselines methods: RESCAL, DistMult, ER-MLP, TransE'
)

parser.add_argument('--model', default='ermlp', metavar='',
                    help='model to run: {rescal, distmult, ermlp, transe} (default: rescal)')
parser.add_argument('--dataset', default='fb15k', metavar='',
                    help='dataset to be used: {wordnet, fb15k} (default: wordnet)')
parser.add_argument('--k', type=int, default=100, metavar='',
                    help='embedding dim (default: 50)')
parser.add_argument('--transe_gamma', type=float, default=1, metavar='',
                    help='TransE loss margin (default: 1)')
parser.add_argument('--transe_metric', default='l2', metavar='',
                    help='whether to use `l1` or `l2` metric for TransE (default: l2)')
parser.add_argument('--mlp_h', type=int, default=100, metavar='',
                    help='size of ER-MLP hidden layer (default: 100)')
parser.add_argument('--mlp_dropout_p', type=float, default=0, metavar='',
                    help='Probability of dropping out neuron in dropout (default: 0)')
parser.add_argument('--ntn_slice', type=int, default=4, metavar='',
                    help='number of slices used in NTN (default: 4)')
parser.add_argument('--mbsize', type=int, default=100, metavar='',
                    help='size of minibatch (default: 100)')
parser.add_argument('--negative_samples', type=int, default=10, metavar='',
                    help='number of negative samples per positive sample  (default: 10)')
parser.add_argument('--nepoch', type=int, default=5, metavar='',
                    help='number of training epoch (default: 5)')
parser.add_argument('--average_loss', default=False, action='store_true',
                    help='whether to average or sum the loss over minibatch')
parser.add_argument('--lr', type=float, default=0.001, metavar='',
                    help='learning rate (default: 0.1)')
parser.add_argument('--lr_decay_every', type=int, default=10, metavar='',
                    help='decaying learning rate every n epoch (default: 10)')
parser.add_argument('--weight_decay', type=float, default=1e-4, metavar='',
                    help='L2 weight decay (default: 1e-4)')
parser.add_argument('--embeddings_lambda', type=float, default=1e-2, metavar='',
                    help='prior strength for embeddings. Constraints embeddings norms to at most one  (default: 1e-2)')
parser.add_argument('--normalize_embed', default=False, type=bool, metavar='',
                    help='whether to normalize embeddings to unit euclidean ball (default: False)')
parser.add_argument('--log_interval', type=int, default=100, metavar='',
                    help='interval between training status logs (default: 100)')
parser.add_argument('--checkpoint_dir', default='models/', metavar='',
                    help='directory to save model checkpoint, saved every epoch (default: models/)')
parser.add_argument('--use_gpu', default=False, action='store_true',
                    help='whether to run in the GPU')
parser.add_argument('--randseed', default=9999, type=int, metavar='',
                    help='resume the training from latest checkpoint (default: False')
parser.add_argument('--test', default=False, action='store_true',
                    help='Activate test mode: gather results on test set only with trained model.')
parser.add_argument('--test_model', default=None, metavar='',
                    help='Model name used for testing, the full path will be appended automatically')

args = parser.parse_args()


# Set random seed
np.random.seed(args.randseed)
torch.manual_seed(args.randseed)

if args.use_gpu:
    torch.cuda.manual_seed(args.randseed)


# Load dictionary lookups
idx2ent = np.load('data/{}/bin/idx2ent.npy'.format(args.dataset))
idx2rel = np.load('data/{}/bin/idx2rel.npy'.format(args.dataset))

n_e = len(idx2ent)
n_r = len(idx2rel)

# Load dataset
X_train = np.load('data/{}/bin/train.npy'.format(args.dataset))
X_val = np.load('data/{}/bin/val.npy'.format(args.dataset))

M_train = X_train.shape[0]
M_val = X_val.shape[0]

lr = args.lr
wd = args.weight_decay
lam = args.embeddings_lambda
C = args.negative_samples

# Initialize model
models = {
    'rescal': RESCAL(n_e=n_e, n_r=n_r, k=args.k, lam=lam, gpu=args.use_gpu),
    'distmult': DistMult(n_e=n_e, n_r=n_r, k=args.k, lam=lam, gpu=args.use_gpu),
    'ermlp': ERMLP(n_e=n_e, n_r=n_r, k=args.k, h_dim=args.mlp_h, p=args.mlp_dropout_p, lam=lam, gpu=args.use_gpu),
    'transe': TransE(n_e=n_e, n_r=n_r, k=args.k, gamma = args.transe_gamma, gpu=args.use_gpu)
}

model = models[args.model]

# Training params
solver = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=wd)
n_epoch = args.nepoch
mb_size = args.mbsize  # 2x with negative sampling
print_every = args.log_interval
checkpoint_dir = '{}/{}'.format(args.checkpoint_dir.rstrip('/'), args.dataset)
checkpoint_path = '{}/{}_lr{}_wd{}.bin'.format(checkpoint_dir, args.model, lr, wd)

if not os.path.exists(checkpoint_dir):
    os.makedirs(checkpoint_dir)


"""
Test mode: Evaluate trained model on test set
=============================================
"""
if args.test:
    X_test = np.load('data/{}/bin/test.npy'.format(args.dataset))

    try:
        filter_s_test = np.load('data/{}/bin/filter_s_test.npy'.format(args.dataset))
        filter_o_test = np.load('data/{}/bin/filter_o_test.npy'.format(args.dataset))
    except:
        filter_s_test = None
        filter_o_test = None

    model_name = '{}/{}.bin'.format(checkpoint_dir, args.test_model)
    state = torch.load(model_name, map_location=lambda storage, loc: storage)
    model.load_state_dict(state)

    model.eval()

    hits_ks = [1, 3, 10]

    # Use entire test set
    mr, mrr, hits = eval_embeddings_vertical(
        model, X_test, n_e, hits_ks, filter_s_test, filter_o_test, n_sample=None
    )

    hits1, hits3, hits10 = hits

    print('MR: {:.4f}; MRR: {:.4f}; Hits@1: {:.4f}; Hits@3: {:.4f}; Hits@10: {:.4f}'
          .format(mr, mrr, hits1, hits3, hits10))

    # Quit immediately
    exit(0)


"""
Train mode: Train model from scratch
====================================
"""
# Begin training
for epoch in range(n_epoch):
    print('Epoch-{}'.format(epoch+1))
    print('----------------')

    it = 0

    # Shuffle and chunk data into minibatches
    mb_iter = get_minibatches(X_train, mb_size, shuffle=True)

    # Anneal learning rate
    lr = args.lr * (0.5 ** (epoch // args.lr_decay_every))
    for param_group in solver.param_groups:
        param_group['lr'] = lr

    for X_mb in mb_iter:
        start = time()

        # Build batch with negative sampling
        m = X_mb.shape[0]

        # C x M negative samples
        X_neg_mb = np.vstack([sample_negatives(X_mb, n_e) for _ in range(C)])

        X_train_mb = np.vstack([X_mb, X_neg_mb])
        y_true_mb = np.vstack([np.ones([m, 1]), np.zeros([m, 1])])

        # Training step
        y = model.forward(X_train_mb)

        y_pos, y_neg = y[:m], y[m:]

        loss = model.ranking_loss(
            y_pos, y_neg, margin=args.transe_gamma, C=C, average=args.average_loss
        )

        loss.backward()
        solver.step()
        solver.zero_grad()

        if args.normalize_embed:
            model.normalize_embeddings()

        end = time()

        # Training logs
        if args.log_interval != -1 and it % print_every == 0:
            model.eval()

            hits_ks = [1, 3, 10]

            # Only use 100 samples of X_val
            mr, mrr, hits = eval_embeddings_vertical(model, X_val, n_e, hits_ks, n_sample=500)

            hits1, hits3, hits10 = hits

            # For TransE, show loss, mrr & hits@10
            print('Iter-{}; loss: {:.4f}; val_mr: {:.4f}; val_mrr: {:.4f}; val_hits@1: {:.4f}; val_hits@3: {:.4f}; val_hits@10: {:.4f}; time per batch: {:.2f}s'
                    .format(it, loss.data[0], mr, mrr, hits1, hits3, hits10, end-start))

            model.train()

        it += 1

    print()

    # Checkpoint every epoch
    torch.save(model.state_dict(), checkpoint_path)
