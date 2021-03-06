import numpy as np
import pandas as pd
from inspect import getmembers, isfunction
from sklearn.utils import shuffle as skshuffle
from time import time

import kga.metrics


def sample_negatives(X, n_e):
    """
    Perform negative sampling by corrupting head or tail of each triplets in
    dataset.

    Params:
    -------
    X: int matrix of M x 3, where M is the (mini)batch size
        First column contains index of head entities.
        Second column contains index of relationships.
        Third column contains index of tail entities.

    n_e: int
        Number of entities in dataset.

    Returns:
    --------
    X_corr: int matrix of M x 3, where M is the (mini)batch size
        Similar to input param X, but at each column, either first or third col
        is subtituted with random entity.
    """
    M = X.shape[0]

    corr = np.random.randint(n_e, size=M)
    e_idxs = np.random.choice([0, 2], size=M)

    X_corr = np.copy(X)
    X_corr[np.arange(M), e_idxs] = corr

    return X_corr


def sample_negatives2(X, n_e):
    """
    Perform negative sampling by corrupting head or tail of each triplets in
    dataset.
    In this function, the replacement entities will be guaranteed to be
    different to the original entities.

    Params:
    -------
    X: int matrix of M x 3, where M is the (mini)batch size
        First column contains index of head entities.
        Second column contains index of relationships.
        Third column contains index of tail entities.

    n_e: int
        Number of entities in dataset.

    Returns:
    --------
    X_corr: int matrix of M x 3, where M is the (mini)batch size
        Similar to input param X, but at each row, either first or third column
        is subtituted with random entity.
    """
    M = X.shape[0]
    X_corr = []

    for x in X:
        h, t = x[0], x[2]

        hc = np.random.randint(n_e)
        while hc == h: hc = np.random.randint(n_e)

        r = x[1]

        tc = np.random.randint(n_e)
        while tc == t: tc = np.random.randint(n_e)

        X_corr.append([hc, r, t])
        X_corr.append([h, r, tc])

    return np.array(X_corr, dtype=int)


def sample_negatives_decoupled(X, n_s, n_o):
    """
    Perform negative sampling by corrupting head or tail of each triplets in
    dataset. This method differs from `sample_negatives(X, n_e)` in a way that
    this method consider the fact that subject set != object set.

    Params:
    -------
    X: int matrix of M x 3, where M is the (mini)batch size
        First column contains index of head entities.
        Second column contains index of relationships.
        Third column contains index of tail entities.

    n_s: int
        Number of subjects in dataset.

    n_o: int
        Number of objects in dataset.

    Returns:
    --------
    X_corr: int matrix of M x 3, where M is the (mini)batch size
        Similar to input param X, but at each column, either first or third col
        is subtituted with random entity.
    """
    M = X.shape[0]

    idxs = np.random.choice([0, 2], size=M)
    mask_s = np.where(idxs == 0)
    mask_o = np.where(idxs == 2)

    n_idxs_s = (idxs == 0).sum()
    n_idxs_o = (idxs == 2).sum()

    corr_s = np.random.randint(n_s, size=n_idxs_s)
    corr_o = np.random.randint(n_o, size=n_idxs_o)

    X_corr = np.copy(X)

    X_corr[mask_s, 0] = corr_s
    X_corr[mask_o, 2] = corr_o

    return X_corr


def sample_negatives_rel(X, n_r):
    M = X.shape[0]
    X_corr = []

    for x in X:
        h, r, t = x[0], x[1], x[2]

        rc = np.random.randint(n_r)
        while rc == r: rc = np.random.randint(n_r)

        X_corr.append([h, rc, t])

    return np.array(X_corr, dtype=int)


def get_dictionary(dataset_dir):
    """
    Let X be file consists of triples, return idx2ent and idx2rel dictionaries.

    Params:
    -------
    dataset_dir: string
        Path to directory containing train.txt, valid.txt, test.txt.

    Returns:
    --------
    idx2ent: np.array of n_e
        List of unique entities.

    idx2rel: np.array of n_r
        List of unique relations.
    """
    dataset_dir = dataset_dir.rstrip('/')

    idx2ent = set()
    idx2rel = set()

    for f_name in ['train.txt', 'valid.txt', 'test.txt']:
        df = pd.read_csv('{}/{}'.format(dataset_dir, f_name), sep='\t', header=None)

        s = set(df[0])
        o = set(df[2])

        idx2ent = idx2ent.union(s.union(o))
        idx2rel = idx2rel.union(set(df[1].unique()))

    return np.array(list(idx2ent)), np.array(list(idx2rel))


def load_dictionary(file_path):
    """
    Load (unique) entity or relation list. To be used as dictionary lookup,
    translating unique index to the real entity/relation name.

    Params:
    -------
    file_path: string
        Path to the list. Should be a text file with one column, one entity/
        relation per line.

    Returns:
    --------
    idx2name: list
        List of all entities/relations. Given an entity/relation index `i`, call
        `idx2name[i]` to get the real entity/relation name.
    """
    df = pd.read_csv(file_path, sep='\t', header=None)
    idx2name = df[0].tolist()
    return idx2name


def load_data(file_path, idx2ent, idx2rel):
    """
    Load raw dataset into tensor of indexes. Use this first for the training
    set, and save the idx2ent and idx2rel as dictionary lookups. When loading
    the validation and test sets, pass those into this function so that the
    consistency is preserved.

    Params:
    -------
    file_path: string
        Path to the dataset file. The dataset should be CSV with 3 columns
        separated by \t.

    idx2ent: array or list
        When called with `idx2ent[i]`, then it returns the real name of the
        i-th entity.

    idx2rel: array or list
        When called with `idx2rel[i]`, then it returns the real name of the
        i-th relation.

    Returns:
    --------
    X: np.array of M x 3
        Contains the triplets from dataset. The entities and relations are
        translated to its unique indices.

    y: [Only if the dataset contains this information] binary np.array of Mx1
        Class label of each M data.
    """
    df = pd.read_csv(file_path, sep='\t', header=None)

    M = df.shape[0]  # dataset size

    # Invert [idx2rel: idx -> entity] to [rel2idx: entity -> idx]
    ent2idx = {e: idx for idx, e in enumerate(idx2ent)}
    rel2idx = {r: idx for idx, r in enumerate(idx2rel)}

    X = np.zeros([M, 3], dtype=int)

    for i, row in df.iterrows():
        X[i, 0] = ent2idx[row[0]]
        X[i, 1] = rel2idx[row[1]]
        X[i, 2] = ent2idx[row[2]]

    # Check if labels exists
    if df.shape[1] >= 4:
        y = df[3].values
        return X, y
    else:
        return X


def get_minibatches(X, mb_size, shuffle=True):
    """
    Generate minibatches from given dataset for training.

    Params:
    -------
    X: np.array of M x 3
        Contains the triplets from dataset. The entities and relations are
        translated to its unique indices.

    mb_size: int
        Size of each minibatch.

    shuffle: bool, default True
        Whether to shuffle the dataset before dividing it into minibatches.

    Returns:
    --------
    mb_iter: generator
        Example usage:
        --------------
        mb_iter = get_minibatches(X_train, mb_size)
        for X_mb in mb_iter:
            // do something with X_mb, the minibatch
    """
    minibatches = []
    X_shuff = np.copy(X)

    if shuffle:
        X_shuff = skshuffle(X_shuff)

    for i in range(0, X_shuff.shape[0], mb_size):
        yield X_shuff[i:i + mb_size]


def get_random_minibatch(X, mb_size):
    """
    Return a single random minibatch of size `mb_size` out of dataset `X`.

    Params:
    -------
    X: np.array of M x 3
        Contains the triplets from dataset. The entities and relations are
        translated to its unique indices.

    mb_size: int
        Size of the minibatch.

    Returns:
    --------
    X_mb: np.array of mb_size x 3
        Each rows is a randomly chosen (without replacement) from X.
    """
    idxs = np.random.choice(np.arange(X.shape[0]), size=mb_size, replace=False)
    return X[idxs, :]


def find_clf_threshold(model, X, y_true, increment=0.01, reverse=False):
    """
    Find binary classification threshold given a model which produces scores.

    Params:
    -------
    model: kga.Model
        Model that generates scores over the data.

    X: np.array of M x 3
        Contains the triplets from dataset. The entities and relations are
        translated to its unique indices.

    y_true: np.array of M x 1
        Contains the correct labels.

    reverse: bool, default: False
        If it is True, then classify (y <= thresh) to be 1.

    Returns:
    --------
    thresh: float
        Number that can be used for thresholding the scores to obtain class
        labels.
    """
    thresh = 0
    best_acc = 0

    y_pred = model.predict(X)
    min_score, max_score = np.min(y_pred), np.max(y_pred)

    for t in np.arange(min_score, max_score, step=increment):
        acc = kga.metrics.accuracy(y_pred, y_true, thresh=t, reverse=reverse)

        if acc > best_acc:
            thresh = t
            best_acc = acc

    return thresh


def inherit_docstrings(cls):
    """
    Decorator to inherit docstring of class/method
    """
    for name, func in getmembers(cls, isfunction):
        if func.__doc__:
            continue

        parent = cls.__mro__[1]

        if hasattr(parent, name):
            func.__doc__ = getattr(parent, name).__doc__

    return cls
