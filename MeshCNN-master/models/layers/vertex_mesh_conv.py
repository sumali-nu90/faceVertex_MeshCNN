import torch
import torch.nn as nn
import torch.nn.functional as F

class VertexMeshConv(nn.Module):
    def __init__(self, in_channels, out_channels, bias=True, symm_oper=None, n_neighbors=6, neighbor_order='random'):
        super(VertexMeshConv, self).__init__()
        self.symm_oper = symm_oper
        self.n_neighbors = n_neighbors
        self.neighbor_order = neighbor_order

        # Set the size of the convolutional filter
        if n_neighbors == 0:
            self.k = 1
        else:
            if 'sum' in neighbor_order:
                self.k = 2
            elif neighbor_order in ['mean_c', 'gaussian_c', 'median_d']:
                self.k = 4
            else:
                self.k = 1 + self.n_neighbors

        self.conv = nn.Conv2d(in_channels=in_channels, out_channels=out_channels, kernel_size=(1, self.k),
                              bias=bias)

    def forward(self, x, mesh):
        x = x.squeeze(-1)

        # build 'neighborhood image' and apply convolution
        if self.n_neighbors == -1:
            G = self.create_GeMM_average(x, mesh)
        else:
            G = torch.cat([self.pad_gemm(i, x.shape[2], x.device) for i in mesh], 0)

        G = self.create_GeMM(x, G)

        return self.conv(G)

    def create_GeMM_average(self, x, mesh):
        G = torch.cat((x.unsqueeze(3), torch.ones(x.shape[0], x.shape[1], x.shape[2], 1).to(x.device)), 3)

        for i in range(mesh.shape[0]):
            for j in range(mesh[i].vs.shape[0]):
                G[i, :, j, 1] = torch.mean(x[i, :, np.fromiter(mesh[i].gemm_vs[j], int, len(mesh[i].gemm_vs[j]))],
                                           dim=1)

        return G

    def flatten_gemm_inds(self, Gi):
        (b, ne, nn) = Gi.shape
        ne += 1
        batch_n = torch.floor(torch.arange(b * ne, device=Gi.device).float() / ne).view(b, ne)
        add_fac = batch_n * ne
        add_fac = add_fac.view(b, ne, 1)
        add_fac = add_fac.repeat(1, 1, nn)
        Gi = Gi.float() + add_fac[:, 1:, :]
        return Gi

    def create_GeMM(self, x, Gi):
        Gishape = Gi.shape
        padding = torch.zeros((x.shape[0], x.shape[1], 1), requires_grad=True, device=x.device)
        x = torch.cat((padding, x), dim=2)
        Gi = Gi + 1

        Gi_flat = self.flatten_gemm_inds(Gi)
        Gi_flat = Gi_flat.view(-1).long()

        odim = x.shape
        x = x.permute(0, 2, 1).contiguous()
        x = x.view(odim[0] * odim[2], odim[1])

        f = torch.index_select(x, dim=0, index=Gi_flat)
        f = f.view(Gishape[0], Gishape[1], Gishape[2], -1)
        f = f.permute(0, 3, 1, 2)

        if 'sum' in self.neighbor_order:
            return torch.cat([f[:, :, :, 0].unsqueeze(3), torch.sum(f[:, :, :, 1:], axis=3).unsqueeze(3)], dim=3)
        else:
            return f

    def pad_gemm_random(self, m, xsz, device):
        rand_gemm = -np.ones((m.vs.shape[0], self.n_neighbors), dtype=int)
        for i, gemm in enumerate(m.gemm_vs):
            if self.n_neighbors > len(gemm):
                rand_gemm[i, 0:len(gemm)] = np.array(list(gemm))
            else:
                rand_gemm[i,:] = np.array(random.sample(gemm,self.n_neighbors))
        padded_gemm = torch.tensor(rand_gemm, device=device).float()
        padded_gemm = padded_gemm.requires_grad_()
        padded_gemm = torch.cat((torch.arange(m.vs.shape[0], device=device).float().unsqueeze(1), padded_gemm), dim=1)
        padded_gemm = F.pad(padded_gemm, (0, 0, 0, xsz - m.vs.shape[0]), "constant", 0)
        padded_gemm = padded_gemm.unsqueeze(0)
        return padded_gemm

    def pad_gemm(self, m, xsz, device):
        padded_gemm = torch.tensor(m.gemm_vs, device=device).float()
        padded_gemm = padded_gemm.requires_grad_()
        padded_gemm = torch.cat((torch.arange(m.vs.shape[0], device=device).float().unsqueeze(1), padded_gemm), dim=1)
        padded_gemm = F.pad(padded_gemm, (0, 0, 0, xsz - m.vs.shape[0]), "constant", 0)
        padded_gemm = padded_gemm.unsqueeze(0)
        return padded_gemm
