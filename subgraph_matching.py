import numpy as np
import networkx as nx
import graph


DEBUG = False


class subgraph_matching():
    def __init__(self,
                 source,
                 motif_edgelist,
                 motif_adj = None,
                 n_components=100,
                 MCMC_iterations=500,
                 is_Glauber=True):
        '''
        Use MCMC Glauber chain to find isomorphic copy of a given motif F inside a graph G

        Sampling isomorhpic copy of motif F
        \approx Sampling homomorphic copy of motif F
        \approx Sampling homomorphic copy of a spanning tree T of F

        Then our MC will explore the space of the homomorphic copies of T, and we can ask whether
        the induced subgraph is actually an isomorphic copy of F
        '''
        self.source = source
        self.n_components = n_components
        self.MCMC_iterations = MCMC_iterations
        self.motif_edgelist = motif_edgelist # list of edges of the motif what we want to find inside the worlds graph G
        self.motif_adj = motif_adj
        self.is_Glauber = is_Glauber

        # read in networks
        A = network_adj_from_path(source) + 0.3
        A[A>1] = 1
        self.A = A
        # read in and set up motif and its spanning tree
        # motif = graph.Graph(1)
        if self.motif_adj is None:
            self.motif = motif_from_edgelist(self.motif_edgelist)
        else:
            self.motif = motif_from_adj(self.motif_adj)

    def read_networks(self, path):
        G = nx.read_edgelist(path, delimiter=',')
        A = nx.to_numpy_matrix(G)
        A = np.squeeze(np.asarray(A))
        print(A.shape)
        # A = A / np.max(A)
        return A

    def path_adj(self, k1, k2):
        # generates adjacency matrix for the path motif of k1 left nodes and k2 right nodes
        if k1 == 0 or k2 == 0:
            k3 = max(k1,k2)
            A = np.eye(k3 + 1, k=1, dtype=int)
        else:
            A = np.eye(k1+k2+1, k=1, dtype = int)
            A[k1,k1+1] = 0
            A[0,k1+1] = 1
        return A

    def indices(self, a, func):
        return [i for (i, val) in enumerate(a) if func(val)]

    def tree_sample(self, B, x):
        # A = N by N matrix giving edge weights on networks
        # B = adjacency matrix of the tree motif rooted at first node
        # Nodes in tree B is ordered according to the depth-first-ordering
        # samples a tree B from a given pivot x as the first node

        A = self.A
        k = len(self.motif.MST_adj)
        N = np.shape(A)[0]
        emb = np.ones(k).astype(int)  # initialize path embedding
        emb[0] = x
        parent = self.motif.MST_parent  # array of length len(B) --
        # ith entry gives the index of the parent of node i in the motif
        ordering = self.motif.MST_ordering
        # print('ordering', ordering)
        # print('edgelist_len', len(self.motif.MSTedges))
        # print('ordering_size', len(ordering))
        # print('B.shape', B.shape)

        if sum(sum(B)) == 0:  # B is a set of isolated nodes
            y = np.random.randint(N, size=(1, k - 1))
            y = y[0]  # just to make it an array
            emb = y
        else:
            for i in np.arange(1, k):
                # print('i', i)
                # print('ordering[i]', ordering[i])
                j = parent[ordering[i]]
                if sum(A[emb[j], :]) > 0:
                    dist = A[emb[j], :] / sum(A[emb[j], :])
                    y = np.random.choice(np.arange(0, N), p=dist)
                else:
                    y = emb[j]
                    print('tree_sample_failed:isolated')
                emb[ordering[i]] = y

        return emb

    def glauber_gen_update(self, B, emb):
        # A = N by N matrix giving edge weights on networks
        # emb = current embedding of the tree motif with adj mx B
        # updates the current embedding using Glauber rule

        A = self.A
        [N, N] = np.shape(A)
        [k, k] = np.shape(B)

        if k == 1:
            # emb[0] = np.random.choice(np.arange(0, N))
            # If B has no edge, conditional measure is uniform over the nodes

            emb[0] = self.RW_update(emb[0])
            # print('Glauber chain updated via RW')
        else:
            j = np.random.choice(np.arange(0, k))  # choose a random node to update
            nbh_in = self.indices(B[:, j], lambda x: x == 1)  # indices of nbs of j in B
            nbh_out = self.indices(B[j, :], lambda x: x == 1)  # indices of nbs of j in B

            # build distribution for resampling emb[j] and resample emb[j]
            dist = np.ones(N, dtype=int)
            for r in nbh_in:
                dist = dist * A[emb[r], :]
            for r in nbh_out:
                dist = dist * np.transpose(A[:, emb[r]])
            if sum(dist) > 0:
                dist = dist / sum(dist)
                y = np.random.choice(np.arange(0, N), p=dist)
                emb[j] = y
            else:
                emb[j] = np.random.choice(np.arange(0, N))
                print('Glauber move rejected')  # Won't happen once valid embedding is established
        return emb

    def RW_update(self, x):
        # A = N by N matrix giving edge weights on networks
        # x = RW is currently at site x
        # stationary distribution = uniform

        A = self.A
        [N, N] = np.shape(A)
        dist_x = np.maximum(A[x, :], np.transpose(A[:, x]))
        # dist_x = A[x,:]
        #  dist_x = np.where(dist_x > 0, 1, 0)  # make 1 if positive, otherwise 0
        # (!!! The above line seem to cause disagreement b/w Pivot and Glauber chains in WAN data for
        # k1=0 and k2=1 case and other inner edge CHD cases -- 9/30/19)

        if sum(dist_x) > 0:  # this holds if the current location x of pivot is not isolated
            dist_x_new = dist_x / sum(dist_x)  # honest symmetric RW kernel
            y = np.random.choice(np.arange(0, N), p=dist_x_new)  # proposed move

            # Use MH-rule to accept or reject the move
            # Use another coin flip (not mess with the kernel) to keep the computation local and fast
            dist_y = np.maximum(A[y, :], np.transpose(A[:, y]))
            # (!!! Symmetrizing the edge weight here does not seem to affect the convergence rate for WAN data)
            # dist_y = A[y, :]
            # prop_accept = min(1, A[y, x] * sum(dist_y) / (sum(dist_x) * A[x, y]))
            prop_accept = min(1, sum(dist_x) / sum(dist_y))

            if np.random.rand() > prop_accept:
                y = x  # move to y rejected

        else:  # if the current location is isolated, uniformly choose a new location
            y = np.random.choice(np.arange(0, N))
        return y

    def pivot_acceptance_prob(self, x, y):
        # approximately compute acceptance probability for moving the pivot of B from x to y
        A = self.A
        k = self.k1 + self.k2 + 1
        accept_prob = sum(A[y, :]) ** (k - 2) / sum(A[x, :]) ** (k - 2)  # to be modified

        return accept_prob

    def RW_update_gen(self, x):
        # A = N by N matrix giving edge weights on networks
        # x = RW is currently at site x
        # Acceptance prob will be computed by conditionally embedding the rest of B pivoted at x and y

        A = self.A
        [N, N] = np.shape(A)
        dist_x = np.maximum(A[x, :], np.transpose(A[:, x]))
        # dist_x = A[x,:]
        #  dist_x = np.where(dist_x > 0, 1, 0)  # make 1 if positive, otherwise 0
        # (!!! The above line seem to cause disagreement b/w Pivot and Glauber chains in WAN data for
        # k1=0 and k2=1 case and other inner edge CHD cases -- 9/30/19)

        if sum(dist_x) > 0:  # this holds if the current location x of pivot is not isolated
            dist_x_new = dist_x / sum(dist_x)  # honest symmetric RW kernel
            y = np.random.choice(np.arange(0, N), p=dist_x_new)  # proposed move

            accept_prob = self.pivot_acceptance_prob(x, y)
            if np.random.rand() > accept_prob:
                y = x  # move to y rejected

        else:  # if the current location is isolated, uniformly choose a new location
            y = np.random.choice(np.arange(0, N))
        return y

    def Pivot_update(self, B, emb):
        # A = N by N matrix giving edge weights on networks
        # emb = current embedding of the motif MST in the network
        # updates the current embedding using pivot rule

        x0 = emb[0]  # current location of pivot
        x0 = self.RW_update(x0)  # new location of the pivot
        emb_new = self.tree_sample(B, x0)  # new path embedding
        return emb_new

    def check_injectivity(self, emb):
        # check if the current homomorphism (emb) is injective
        nodelist = []
        for i in np.arange(len(emb)):
            nodelist.append(emb[i])
        size = len(set(nodelist))
        return (len(emb) == size)  # emb injective if True

    def find_subgraph_hom(self, iterations):
        # B = adjacency matrix of the input subgraph that we want to find inside the world graph with adj A
        A = self.A
        N = A.shape[0]
        B = np.asarray(self.motif.MST_adj).astype(int)  # adjacency matrix of a spanning tree of the motif
        C = np.asarray(self.motif.adj).astype(int)  # full adjacency matrix of the motif
        x0 = np.random.choice(np.arange(0, N))
        # x0 = 12000
        emb = self.tree_sample(B, x0)  # initialize embedding of B into A

        subgraph_hom_list = []  # node list of homomorphic copies of the motif we found
        subgraph_iso_list = []  # node list of isomorphic copies of the motif we found
        count_hom = 1
        count_iso = 1
        for step in np.arange(iterations):
            if self.is_Glauber:
                emb = self.glauber_gen_update(B, emb)  # update current embedding
            else:
                emb = self.Pivot_update(B, emb)  # update current embedding
            # print('emb', emb)

            adj = np.zeros(shape=(len(emb), len(emb))).astype(int)
            for i in np.arange(len(emb)):
                for j in np.arange(len(emb)):
                    adj[i, j] = A[emb[i], emb[j]]

            if np.linalg.norm(C - adj) == 0:
                subgraph_hom_list.append(emb)
                print('%i th copy of homomorphism found=' % count_hom, emb)
                count_hom += 1
                if self.check_injectivity(emb):
                    subgraph_iso_list.append(emb)
                    print('%i th copy of isomorhpism found=' % count_iso, emb)
                    count_iso += 1
            print('iteration %i out of %i' % (step, iterations))
        return subgraph_hom_list, subgraph_iso_list


def network_adj_from_path(path):
    edgelist = np.genfromtxt(path, delimiter=',', dtype=int)
    G = graph.Graph(1)
    G.edgelist = edgelist.tolist()
    G.adj = G.edge2adj(G.edgelist)
    return np.asarray(G.adj)

def motif_from_edgelist(edgelist):
    """ Given an edgelist, convert it to an graph object for motif
    Create the motif and compute its minimal spanning tree
    Returns a graph object motif """
    motif = graph.Graph(1)
    motif.edgelist = edgelist
    motif.adj = motif.edge2adj(motif.edgelist)
    motif.V = len(motif.adj)
    motif.MSTedges = motif.primMST()
    motif.MST_adj = motif.edge2adj(motif.MSTedges)
    # motif.MST_parent = motif.MST_parent()
    # motif.MST_ordering = motif.MST_ordering()
    return motif

def motif_from_adj(adj):
    """ Given an adjacency matrix, convert it to an graph object for motif
    Create the motif and compute its minimal spanning tree
    Returns a graph object motif """
    motif = graph.Graph(1)
    adj[adj>1] = 1
    motif.edgelist = motif.adj2edge(adj)
    motif.adj = motif.edge2adj(motif.edgelist)

    # Flatten multiedges to single edges
    # motif.adj[motif.adj>1] = 1
    motif.V = len(adj)
    # motif.edgelist = motif.adj2edge(adj)
    print('edgelist', motif.edgelist)
    motif.MSTedges = motif.primMST()
    motif.MST_adj = motif.edge2adj(motif.MSTedges)
    # motif.MST_parent = motif.MST_parent(motif.)
    # motif.MST_ordering = motif.MST_ordering()
    return motif

def main():
    ### set motif edge list
    # motif_E = [[0,1], [1,2], [0,2]]  # triangle
    # motif_E = [[0, 1], [1, 2], [0, 2], [1, 3], [3, 4]]  # triangle
    motif_E = [[0, 1], [1, 2], [2, 3], [3, 4], [4, 0]]  # cycle
    # print('motif_edgelist', motif_E)

    ### Create list of file names
    myfolder = "Data/Facebook/SchoolDataPythonFormat/sub_fb_networks"
    # onlyfiles = [f for f in listdir(myfolder) if isfile(join(myfolder, f))]
    onlyfiles = ['Caltech36.txt']
    # onlyfiles.remove('desktop.ini')

    for school in onlyfiles:
        directory = "Data/Facebook/SchoolDataPythonFormat/"
        path = directory + school
        print('Currently finding copies of the motif from ' + school)

        subgraph_mining = subgraph_matching(source=path,
                                            motif_edgelist = motif_E,
                                            motif_adj = None, # np.load("motif_adj.npy").astype(int),
                                            MCMC_iterations=5000,
                                            is_Glauber=True)  # MCMC steps (macro, grow with size of ntwk)

        subgraph_list = subgraph_mining.find_subgraph_hom(iterations=5000)
        np.save('Subgraph_list/' + school + '_triangle_list', subgraph_list)
        # print('subgraph_list', subgraph_list)

        # return A_recons, A_overlap_count


if __name__ == '__main__':
    main()
