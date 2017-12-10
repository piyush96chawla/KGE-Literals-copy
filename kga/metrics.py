import numpy as np
import scipy.spatial.distance
from sklearn.metrics import roc_auc_score
from collections import defaultdict
import scipy.stats as st


def accuracy(y_pred, y_true, thresh=0.5, reverse=False):
    """
    Compute accuracy score.

    Params:
    -------
    y_pred: np.array
        Predicted (Bernoulli) probabilities.

    y_true: np.array, binary
        True (Bernoulli) labels.

    thresh: float, default: 0.5
        Classification threshold.

    reverse: bool, default: False
        If it is True, then classify (y <= thresh) to be 1.
    """
    y = (y_pred >= thresh) if not reverse else (y_pred <= thresh)
    return np.mean(y == y_true)


def auc(y_pred, y_true):
    """
    Compute area under ROC curve score.

    Params:
    -------
    y_pred: np.array
        Predicted (Bernoulli) probabilities.

    y_true: np.array, binary
        True (Bernoulli) labels.
    """
    return roc_auc_score(y_true, y_pred)


def eval_embeddings(model, X_test, n_e, k, n_sample=1000, X_lit=None):
    """
    Compute Mean Reciprocal Rank and Hits@k score of embedding model.
    The procedure follows Bordes, et. al., 2011.

    Params:
    -------
    model: kga.Model
        Embedding model to be evaluated.

    X_test: M x 3 matrix, where M is data size
        Contains M test triplets.

    n_e: int
        Number of entities in dataset.

    k: int
        Max rank to be considered, i.e. to be used in Hits@k metric.

    n_sample: int, default: 1000
        Number of negative entities to be considered. These n_sample negative
        samples are randomly picked w/o replacement from [0, n_e). Consider
        setting this to get the (fast) approximation of mrr and hits@k.

    X_lit: n_e x n_l matrix
        Matrix containing all literals for all entities.


    Returns:
    --------
    mrr: float
        Mean Reciprocal Rank.

    hitsk: float
        Hits@k.
    """
    M = X_test.shape[0]

    X_corr_h = np.copy(X_test)
    X_corr_t = np.copy(X_test)

    N = n_sample+1 if n_sample is not None else n_e+1

    scores_h = np.zeros([M, N])
    scores_t = np.zeros([M, N])

    # Gather scores for correct entities
    if X_lit is None:
        y = model.predict(X_test).ravel()
    else:
        X_lit_s_ori = X_lit[X_test[:, 0]]
        X_lit_o_ori = X_lit[X_test[:, 2]]
        y = model.predict(X_test, X_lit_s_ori, X_lit_o_ori).ravel()

    scores_h[:, 0] = y
    scores_t[:, 0] = y

    if n_sample is not None:
        # Gather scores for some random negative entities
        ents = np.random.choice(np.arange(n_e), size=n_sample, replace=False)
    else:
        ents = np.arange(n_e)

    for i, e in enumerate(ents):
        idx = i+1  # as i == 0 is for correct triplet score

        X_corr_h[:, 0] = e
        X_corr_t[:, 2] = e

        if X_lit is None:
            y_h = model.predict(X_corr_h).ravel()
            y_t = model.predict(X_corr_t).ravel()
        else:
            X_lit_s = X_lit[X_corr_h[:, 0]]
            X_lit_o = X_lit[X_corr_t[:, 2]]
            y_h = model.predict(X_corr_h, X_lit_s, X_lit_o_ori).ravel()
            y_t = model.predict(X_corr_t, X_lit_s_ori, X_lit_o).ravel()

        scores_h[:, idx] = y_h
        scores_t[:, idx] = y_t

    ranks_h = np.array([st.rankdata(s)[0] for s in scores_h])
    ranks_t = np.array([st.rankdata(s)[0] for s in scores_t])

    mrr = (np.mean(1/ranks_h) + np.mean(1/ranks_t)) / 2
    hitsk = (np.mean(ranks_h <= k) + np.mean(ranks_t <= k)) / 2

    return mrr, hitsk


def eval_embeddings_rel(model, X_test, n_r, k, X_lit_s=None, X_lit_o=None, X_lit_img=None, X_lit_txt=None):
    """
    Compute Mean Reciprocal Rank and Hits@k score of embedding model by ranking
    relations. The procedure follows Bordes, et. al., 2011.

    Params:
    -------
    model: kga.Model
        Embedding model to be evaluated.

    X_test: M x 3 matrix, where M is data size
        Contains M test triplets.

    n_e: int
        Number of entities in dataset.

    k: int
        Max rank to be considered, i.e. to be used in Hits@k metric.

    X_lit_s: M x n_l_s matrix
        Matrix containing all literals for test subjects.

    X_lit_o: M x n_l_o matrix
        Matrix containing all literals for test objects.


    Returns:
    --------
    mrr: float
        Mean Reciprocal Rank.

    hitsk: float
        Hits@k.
    """
    M = X_test.shape[0]

    X_corr_r = np.copy(X_test)
    scores_r = np.zeros([M, n_r])

    # Gather scores for correct entities
    if X_lit_s is None or X_lit_o is None:
        y = model.predict(X_test).ravel()
    else:
        y = model.predict(X_test, X_lit_s, X_lit_o, X_lit_img, X_lit_txt).ravel()

    scores_r[:, 0] = y

    for i, r in enumerate(np.arange(5)):  # [0 ... 4]
        X_corr_r[:, 1] = r

        if X_lit_s is None or X_lit_o is None:
            y_r = model.predict(X_corr_r).ravel()
        else:
            y_r = model.predict(X_corr_r, X_lit_s, X_lit_o, X_lit_img, X_lit_txt).ravel()

        scores_r[:, i] = y_r

    ranks_r = np.array(
        [st.rankdata(s)[r] for s, r in zip(scores_r, X_test[:, 1])]
    )

    mrr = np.mean(1/ranks_r)
    hitsk = np.mean(ranks_r <= k)

    return mrr, hitsk


def entity_nn(model, n=10, k=5, idx2ent=None):
    """
    Compute nearest neighbours of all entities embeddings of a model.

    Params:
    -------
    model: instance of kga.Model

    n: int, default: 10
        Number of (random) entities to be queried.

    k: int, default: 5
        Number of nearest neighbours.

    idx2ent: dict, default: None
        Lookup dictionary to translate entity indices. If this is None, then
        output the indices matrix instead.
    """
    try:
        emb = model.emb_E.weight.data.numpy()  # m x k
    except:
        emb = model.emb_E.cpu().weight.data.numpy()

    idxs = np.random.randint(emb.shape[0], size=n)
    res = emb[idxs, :]  # n x k

    mat = scipy.spatial.distance.cdist(res, emb, metric='euclidean')  # n x m
    nn = np.argsort(mat, axis=1)[:, :k]  # gather k-bests indexes

    if idx2ent is None:
        return nn

    nn_dict = defaultdict(dict)

    for i, e in enumerate(idxs):
        for j in nn[i]:
            k = idx2ent[e]
            l = idx2ent[j]
            nn_dict[k][l] = mat[i, j]

    return dict(nn_dict)


def relation_nn(model, n=10, k=5, idx2rel=None):
    """
    Compute nearest neighbours of all relations embeddings of a model.

    Params:
    -------
    model: instance of kga.Model

    n: int, default: 10
        Number of (random) relations to be queried.

    k: int, default: 5
        Number of nearest neighbours.

    idx2rel: dict, default: None
        Lookup dictionary to translate relation indices. If this is None, then
        output the indices matrix instead.
    """
    try:
        emb = model.emb_R.weight.data.numpy()  # m x k
    except:
        emb = model.emb_R.cpu().weight.data.numpy()

    idxs = np.random.randint(emb.shape[0], size=n)
    res = emb[idxs, :]  # n x k

    mat = scipy.spatial.distance.cdist(res, emb, metric='euclidean')  # n x m
    nn = np.argsort(mat, axis=1)[:, :k]  # gather k-bests indexes

    if idx2rel is None:
        return nn

    nn_dict = defaultdict(dict)

    for i, e in enumerate(idxs):
        for j in nn[i]:
            k = idx2rel[e]
            l = idx2rel[j]
            nn_dict[k][l] = mat[i, j]

    return dict(nn_dict)
