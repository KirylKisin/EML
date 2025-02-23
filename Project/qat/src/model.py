from torch import nn

from .noise_operator.config import NoNoiseConfig
from .noise_operator.factory import NoiseOperatorFactory
import torch.quantization
from torch.quantization import QuantStub, DeQuantStub

# fmt: off
cfg = {
    'LeNet5': ['C6@5', 'ReLU', 'M2', 'C16@5', 'ReLU', 'M2', 'Flatten', 'FC120', 'ReLU', 'FC84', 'ReLU', ],
    'LeNet5-BN': ['C6@5', 'BN2d', 'ReLU', 'M2', 'C16@5', 'BN2d', 'ReLU', 'M2', 'Flatten', 'FC120', 'BN1d',
                  'ReLU', 'FC84', 'BN1d', 'ReLU', ],
    'LeNet5-BN-noNoise': ['C6@5', 'BN2d-NN', 'ReLU', 'M2', 'C16@5', 'BN2d-NN', 'ReLU', 'M2', 'Flatten', 'FC120',
                          'BN1d-NN',
                          'ReLU', 'FC84', 'BN1d-NN', 'ReLU', ],
    'CNN-S': ['C28', 'ReLU', 'C30', 'ReLU', 'Flatten', 'FC128', 'ReLU', ],
    'CNN-S-BN': ['C28', 'BN2d', 'ReLU', 'C30', 'BN2d', 'ReLU', 'Flatten', 'FC128', 'BN1d', 'ReLU', ],
    'CNN-S-BN-noNoise': ['C28', 'BN2d-NN', 'ReLU', 'C30', 'BN2d-NN', 'ReLU', 'Flatten', 'FC128', 'BN1d-NN', 'ReLU', ],
    'CNN-M-BN': ['C64', 'BN2d', 'ReLU', 'C48', 'BN2d', 'ReLU', 'Flatten', 'FC128', 'BN1d', 'ReLU', ],
    'CNN-L-BN': ['C60', 'BN2d', 'ReLU', 'C76', 'BN2d', 'ReLU', 'Flatten', 'FC128', 'BN1d', 'ReLU', ],
}


class LeNet(nn.Module):
    """
    LeNet network, implemented as described in the original paper on page 7: https://www.researchgate.net/profile/Yann-Lecun/publication/2985446_Gradient-Based_Learning_Applied_to_Document_Recognition/links/0deec519dfa1983fc2000000/Gradient-Based-Learning-Applied-to-Document-Recognition.pdf?origin=publication_detail
    Also inspired by: https://github.com/ChawDoe/LeNet5-MNIST-PyTorch/blob/master/model.py
    """
    def __init__(self,
                 conf_name='LeNet5',
                 input_shape=(1, 28, 28),
                 default_noise_config=NoNoiseConfig(),
                 layer_wise_noise_config=dict(),
                 num_classes=10,
                 q = False,
                 ):
        super().__init__()
        # Makes some noise xD
        self._noise_factory = NoiseOperatorFactory(default_noise_config, layer_wise_config=layer_wise_noise_config)
        self.features, output_channels = self._make_layers(cfg[conf_name], input_shape)
        self.classifier = nn.Sequential(
            nn.Linear(output_channels, num_classes),
            self._noise_factory.get_noise_operator(),
        )

        print(f"Created the following number of noise layers / operators: {self._noise_factory._layer_counter}")
        # Check for out of bounds layer noise configurations
        if self._noise_factory.check_for_unused_configs():
            # fmt: off
            raise ValueError(f"A noise setting for a layer not contained in the network was requested. "
                             f"This is likely due to an incorrect configuration. "
                             f"The built network has {self._noise_factory._layer_counter} noise layers, "
                             f"but layer wise configurations were requested for the following layer indices: "
                             f"{layer_wise_noise_config.keys()}")
        
        self.q = q
        if q:
          self.quant = QuantStub()
          self.dequant = DeQuantStub()

    def forward(self, x):
        if self.q:
          x = self.quant(x)
        out = self.features(x)
        out = self.classifier(out)
        if self.q:
          out = self.dequant(out)
        return out

    def _make_layers(self, config, input_shape):
        layers = [
            self._noise_factory.get_noise_operator(),
        ]
        in_channels = input_shape[0]
        for x in config:
            if x.startswith('M'):
                kernel_size = int(x.split('M')[-1])
                layers += [
                    nn.MaxPool2d(kernel_size),
                    self._noise_factory.get_noise_operator()
                ]
            elif x == 'ReLU':
                layers += [
                    nn.ReLU(),
                    self._noise_factory.get_noise_operator(),
                ]
            elif x.startswith('FC'):
                num_ch = int(x.split('FC')[-1])
                layers += [
                    nn.LazyLinear(num_ch),
                    self._noise_factory.get_noise_operator(),
                ]
                in_channels = num_ch
            elif x.startswith('C'):
                num_ch = int(x.split('C')[-1].split('@')[0])
                kernel_size = int(x.split('C')[-1].split('@')[-1])
                print(f"Conv2d: in_channels={in_channels}, out_channels={num_ch}, kernel_size={kernel_size}")
                layers += [
                    nn.Conv2d(in_channels=in_channels, out_channels=num_ch, kernel_size=kernel_size),
                    self._noise_factory.get_noise_operator(),
                ]
                in_channels = num_ch
            elif x == 'BN2d':
                layers += [
                    nn.BatchNorm2d(in_channels),
                    self._noise_factory.get_noise_operator(),
                ]
            elif x == 'BN1d':
                layers += [
                    nn.BatchNorm1d(in_channels),
                    self._noise_factory.get_noise_operator(),
                ]
            elif x == 'BN2d-NN':
                layers += [
                    nn.BatchNorm2d(in_channels),
                ]
            elif x == 'BN1d-NN':
                layers += [
                    nn.BatchNorm1d(in_channels),
                ]
            elif x == 'Flatten':
                layers += [
                    nn.Flatten(),
                ]
            else:
                raise NotImplementedError
        return nn.Sequential(*layers), in_channels

"""
CNN from the Hello Edged paper.
Implementation originally from here: https://github.com/mlcommons/tiny_results_v0.7/blob/691f8b26aa9dffa09b1761645d4a35ad35a4f095/open/hls4ml-finn/code/kws/KWS-W3A3/training/model/models.py#L123
"""

class CNN_HE(nn.Module):
    """
    Convolutional network, based on this implementation: https://github.com/ARM-software/ML-KWS-for-MCU/blob/8151349b110f4d1c194c085fcc5b3535bdf7ce4a/models.py#L643
    NOTE: This network does not contain the low-rank linear layer as described in the original paper.
    """
    def __init__(self,
                 conf_name='CNN-S-BN',
                 input_shape=(1, 10, 49),
                 default_noise_config=NoNoiseConfig(),
                 layer_wise_noise_config=dict(),
                 num_classes=12,
                 q = False,
                 ):
        # :)
        super().__init__()

        # Makes some noise xD
        self._noise_factory = NoiseOperatorFactory(default_noise_config, layer_wise_config=layer_wise_noise_config)
        self.features, output_channels = self._make_layers(cfg[conf_name], input_shape)
        self.classifier = nn.Sequential(
            nn.Linear(output_channels, num_classes),
            self._noise_factory.get_noise_operator(),
        )

        print(f"Created the following number of noise layers / operators: {self._noise_factory._layer_counter}")
        # Check for out of bounds layer noise configurations
        if self._noise_factory.check_for_unused_configs():
            raise ValueError(f"A noise setting for a layer not contained in the network was requested. "
                             f"This is likely due to an incorrect configuration. "
                             f"The built network has {self._noise_factory._layer_counter} noise layers, "
                             f"but layer wise configurations were requested for the following layer indices: "
                             f"{layer_wise_noise_config.keys()}")
        
        self.q = q
        if q:
          self.quant = QuantStub()

    def forward(self, x):
        if self.q:
          x = self.quant(x)
        out = self.features(x)
        out = self.classifier(out)
        if self.q:
          out = self.dequant(out)
        return out

    def _make_layers(self, config, input_shape):
        layers = [
            self._noise_factory.get_noise_operator(),
        ]
        in_channels = input_shape[0]
        for idx, x in enumerate(config):
            if x.startswith('M'):
                kernel_size = int(x.split('M')[-1])
                layers += [
                    nn.MaxPool2d(kernel_size),
                    self._noise_factory.get_noise_operator()
                ]
            elif x == 'ReLU':
                layers += [
                    nn.ReLU(),
                    self._noise_factory.get_noise_operator(),
                ]
            elif x.startswith('FC'):
                num_ch = int(x.split('FC')[-1])
                layers += [
                    nn.LazyLinear(num_ch),
                    self._noise_factory.get_noise_operator(),
                ]
                in_channels = num_ch
            elif x.startswith('C'):
                num_ch = int(x.split('C')[-1])
                kernel_size = (4, 10)
                if idx > 0:
                    stride = (1, 1)
                else:
                    stride = (1, 2)
                layers += [
                    nn.Conv2d(in_channels=in_channels,
                              out_channels=num_ch,
                              kernel_size=kernel_size,
                              stride=stride,
                              ),
                    self._noise_factory.get_noise_operator(),
                ]
                in_channels = num_ch
            elif x == 'BN2d':
                layers += [
                    nn.BatchNorm2d(in_channels),
                    self._noise_factory.get_noise_operator(),
                ]
            elif x == 'BN1d':
                layers += [
                    nn.BatchNorm1d(in_channels),
                    self._noise_factory.get_noise_operator(),
                ]
            elif x == 'BN2d-NN':
                layers += [
                    nn.BatchNorm2d(in_channels),
                ]
            elif x == 'BN1d-NN':
                layers += [
                    nn.BatchNorm1d(in_channels),
                ]
            elif x == 'Flatten':
                layers += [
                    nn.Flatten(),
                ]
            else:
                raise NotImplementedError
        return nn.Sequential(*layers), in_channels

from torch.nn.modules.batchnorm import _NormBase

class WeightClamper:
    """
    Class for clamping the weights of a given model.
    Inspired by: https://stackoverflow.com/a/70330290
    """
    def __init__(self, min_clamp=None, max_clamp=None):
        self._min = min_clamp
        self._max = max_clamp

    def __call__(self, module):
        # Only continue if something is to be done
        if (self._max is None) and (self._min is None):
            return
        # Only consider layer, which have weights
        if hasattr(module, 'weight'):
            # Skip Batchnorm layers
            if not issubclass(type(module), _NormBase):
                # Clamp weights
                w = module.weight.data
                w = w.clamp(self._min, self._max)
                module.weight.data = w
