import sys
sys.path.append('.')

from kga.models.literals import *
from kga.metrics import *
from kga.util import *
import numpy as np
import torch.optim
import argparse
import os
from time import time
from sklearn.utils import shuffle as skshuffle


parser = argparse.ArgumentParser(
    description='Train ERMLP with literals on YAGO'
)

parser.add_argument('--k', type=int, default=50, metavar='',
                    help='embedding dim (default: 50)')
parser.add_argument('--mlp_h', type=int, default=100, metavar='',
                    help='size of ER-MLP hidden layer (default: 100)')
parser.add_argument('--gamma', type=float, default=1, metavar='',
                    help='Ranking loss margin (default: 1)')
parser.add_argument('--mbsize', type=int, default=100, metavar='',
                    help='size of minibatch (default: 100)')
parser.add_argument('--negative_samples', type=int, default=10, metavar='',
                    help='number of negative samples per positive sample  (default: 10)')
parser.add_argument('--nepoch', type=int, default=20, metavar='',
                    help='number of training epoch (default: 20)')
parser.add_argument('--average_loss', default=False, action='store_true',
                    help='whether to average or sum the loss over minibatch')
parser.add_argument('--lr', type=float, default=0.01, metavar='',
                    help='learning rate (default: 0.01)')
parser.add_argument('--lr_decay_every', type=int, default=20, metavar='',
                    help='decaying learning rate every n epoch (default: 20)')
parser.add_argument('--weight_decay', type=float, default=1e-4, metavar='',
                    help='L2 weight decay (default: 1e-4)')
parser.add_argument('--embeddings_lambda', type=float, default=0, metavar='',
                    help='prior strength for embeddings. Constraints embeddings norms to at most one  (default: 0)')
parser.add_argument('--normalize_embed', default=False, type=bool, metavar='',
                    help='whether to normalize embeddings to unit euclidean ball (default: False)')
parser.add_argument('--log_interval', type=int, default=9999, metavar='',
                    help='interval between training status logs (default: 9999)')
parser.add_argument('--checkpoint_dir', default='models/', metavar='',
                    help='directory to save model checkpoint, saved every epoch (default: models/)')
parser.add_argument('--use_gpu', default=False, action='store_true',
                    help='whether to run in the GPU')
parser.add_argument('--randseed', default=9999, type=int, metavar='',
                    help='resume the training from latest checkpoint (default: False')
parser.add_argument('--test', default=False, action='store_true',
                    help='Activate test mode: gather results on test set only with trained model.')
parser.add_argument('--test_model', default='mtkgnn', metavar='',
                    help='Model name used for testing, the full path will be appended automatically (default: "mtkgnn")')
parser.add_argument('--use_numerical_lit', default=False, action='store_true',
                    help='whether to use numerical literals (default: False)')
parser.add_argument('--use_image_lit', default=False, action='store_true',
                    help='whether to use images literals (default: False)')
parser.add_argument('--use_text_lit', default=False, action='store_true',
                    help='whether to use texts literals (default: False)')

args = parser.parse_args()


# Set random seed
np.random.seed(args.randseed)
torch.manual_seed(args.randseed)

if args.use_gpu:
    torch.cuda.manual_seed(args.randseed)


# Load dictionary lookups
idx2ent = np.load('data/yago3-10-literal/bin/idx2ent.npy')
idx2rel = np.load('data/yago3-10-literal/bin/idx2rel.npy')

n_ent = len(idx2ent)
n_rel = len(idx2rel)

# Load dataset
X_train = np.load('data/yago3-10-literal/bin/train.npy').astype(int)
X_val = np.load('data/yago3-10-literal/bin/val.npy').astype(int)

# Load literals
X_lit = np.load('data/yago3-10-literal/bin/numerical_literals.npy').astype(np.float32)
X_lit_img = np.load('data/yago3-10-literal/bin/image_literals.npy').astype(np.float32)
X_lit_txt = np.load('data/yago3-10-literal/bin/text_literals.npy').astype(np.float32)

# Preprocess literals


def normalize(X, minn, maxx):
    return (X - minn) / (maxx - minn + 1e-8)


max_lit, min_lit = np.max(X_lit, axis=0), np.min(X_lit, axis=0)
X_lit = normalize(X_lit, max_lit, min_lit)

# Preload literals for validation
X_lit_s_val = X_lit[X_val[:, 0]]
X_lit_o_val = X_lit[X_val[:, 2]]
X_lit_s_img_val = X_lit_img[X_val[:, 0]]
X_lit_o_img_val = X_lit_img[X_val[:, 2]]
X_lit_s_txt_val = X_lit_txt[X_val[:, 0]]
X_lit_o_txt_val = X_lit_txt[X_val[:, 2]]

M_train = X_train.shape[0]
M_val = X_val.shape[0]

n_lit = X_lit.shape[1]

k = args.k
h_dim = args.mlp_h
lam = args.embeddings_lambda
C = args.negative_samples

# Initialize model
model = DistMultLiteral(n_ent, n_rel, n_lit, k, args.use_gpu)

# Training params
lr = args.lr
wd = args.weight_decay

solver = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=wd)
n_epoch = args.nepoch
mb_size = args.mbsize
print_every = args.log_interval
model_name = 'distmult_lit'
checkpoint_dir = '{}/yago'.format(args.checkpoint_dir.rstrip('/'))
checkpoint_path = '{}/{}_lr{}_wd{}.bin'.format(checkpoint_dir, model_name, lr, wd)

if not os.path.exists(checkpoint_dir):
    os.makedirs(checkpoint_dir)


"""
Test mode: Evaluate trained model on test set
=============================================
"""
if args.test:
    X_test = np.load('data/yago3-10-literal/bin/test.npy').astype(int)

    filter_s_test = np.load('data/yago3-10-literal/bin/filter_s_test.npy')
    filter_o_test = np.load('data/yago3-10-literal/bin/filter_o_test.npy')

    model_name = '{}/{}.bin'.format(checkpoint_dir, args.test_model)
    state = torch.load(model_name, map_location=lambda storage, loc: storage)
    model.load_state_dict(state)

    model.eval()

    hits_ks = [1, 3, 10]

    # Use entire test set
    # mr, mrr, hits = eval_embeddings_vertical(
    #     model, X_test, n_ent, hits_ks, filter_s_test, filter_o_test, n_sample=None,
    #     X_lit=X_lit, X_lit_img=X_lit_img, X_lit_txt=X_lit_txt
    # )
    mr, mrr, hits = eval_embeddings_vertical(
        model, X_test, n_ent, hits_ks, filter_s_test, filter_o_test, n_sample=100,
        X_lit=X_lit
    )

    hits1, hits3, hits10 = hits

    print('MR: {:.3f}; MRR: {:.4f}; Hits@1: {:.3f}; Hits@3: {:.3f}; Hits@10: {:.3f}'
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
        X_neg_mb = np.vstack([sample_negatives(X_mb, n_ent)
                              for _ in range(C)])

        X_train_mb = np.vstack([X_mb, X_neg_mb])
        y_true_mb = np.vstack([np.ones([m, 1]), np.zeros([m, 1])])

        # Numerical lit
        X_lit_s_mb = X_lit[X_train_mb[:, 0]]
        X_lit_o_mb = X_lit[X_train_mb[:, 2]]
        # Image lit
        # X_lit_s_img_mb = X_lit_img[X_train_mb[:, 0]]
        # X_lit_o_img_mb = X_lit_img[X_train_mb[:, 2]]
        # # Text lit
        # X_lit_s_txt_mb = X_lit_txt[X_train_mb[:, 0]]
        # X_lit_o_txt_mb = X_lit_txt[X_train_mb[:, 2]]

        # Training step
        # y = model.forward(X_train_mb, X_lit_s_mb, X_lit_o_mb, X_lit_s_img_mb,
        #                   X_lit_o_img_mb, X_lit_s_txt_mb, X_lit_o_txt_mb)
        y = model.forward(X_train_mb, X_lit_s_mb, X_lit_o_mb)
        y_pos, y_neg = y[:m], y[m:]

        loss = model.ranking_loss(
            y_pos, y_neg, margin=1, C=C, average=args.average_loss
        )

        loss.backward()
        solver.step()
        solver.zero_grad()

        if args.normalize_embed:
            model.normalize_embeddings()

        end = time()

        # Training logs
        if print_every != -1 and it % print_every == 0:
            hits_ks = [1, 3, 10]

            # mr, mrr, hits = eval_embeddings_vertical(
            #     model, X_val, n_ent, hits_ks, filter_s_val, filter_o_val, n_sample=500,
            #     X_lit=X_lit, X_lit_img=X_lit_img, X_lit_txt=X_lit_txt
            # )
            mr, mrr, hits = eval_embeddings_vertical(
                model, X_val, n_ent, hits_ks, filter_s_val, filter_o_val, n_sample=100,
                X_lit=X_lit
            )

            hits1, hits3, hits10 = hits

            print('Iter-{}; loss: {:.4f}; val_mr: {:.4f}; val_mrr: {:.4f}; val_hits@1: {:.4f}; val_hits@3: {:.4f}; val_hits@10: {:.4f}; time per batch: {:.2f}s'
                  .format(it, loss.data[0], mr, mrr, hits1, hits3, hits10, end-start))

        it += 1

    print()

    # Checkpoint every epoch
    torch.save(model.state_dict(), checkpoint_path)
