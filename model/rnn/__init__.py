import logging
from copy import deepcopy

import numpy as np
import tensorflow as tf
from tensorflow import sigmoid
from tensorflow.contrib.rnn import LayerRNNCell
from tensorflow.python.ops import init_ops
from tensorflow.python.ops import variable_scope as vs
from tensorflow.python.util import nest

from helper import argget, convolution_helper_padding_same, get_modified_xavier_method, get_orthogonal_block_circulant_initialization
from model import batch_norm


class CRNNCell(LayerRNNCell):

    def __init__(self, myshape, num_units, activation=tf.nn.tanh, reuse=None, **kw):
        super(CRNNCell, self).__init__(_reuse=reuse)
        self._activation = activation
        self._num_units = num_units
        self.gate = argget(kw, 'gate', sigmoid)
        self.periodicconvolution_x = argget(kw, 'periodicconvolution_x', False)
        self.periodicconvolution_h = argget(kw, 'periodicconvolution_h', False)
        self.filter_size_x = argget(kw, 'filter_size_x', [7, 7])
        self.filter_size_h = argget(kw, 'filter_size_h', [7, 7])
        self.use_bernoulli = argget(kw, 'use_bernoulli', False)
        self.dropconnectx = argget(kw, "dropconnectx", None)
        self.dropconnecth = argget(kw, "dropconnecth", None)
        self.strides = argget(kw, "strides", None)
        if myshape is None:
            raise Exception('myshape cant be None!')
        myshapein = deepcopy(myshape)
        myshapein.pop(-2)
        myshapeout = deepcopy(myshape)
        myshapeout.pop(-2)
        myshapeout[-1] = self._num_units
        if self.strides is not None:
            if len(myshapeout[1:-1]) != len(self.strides):
                raise Exception('stride shape should match myshapeout[1:-1]! strides: {}, myshape: {}'.format(self.strides, myshapeout))
            myshapeout[1:-1] = [int(np.round((myshapeout[1 + si]) / self.strides[si])) for si in range(len(myshapeout) - 2)]
        self.myshapes = (myshapein, myshapeout)
    @property
    def output_size(self):
        return self._num_units

    @property
    def state_size(self):
        return self._num_units

    def _paddata(self, data, fshape):
        shape = data.get_shape().as_list()
        # we assume we can drop the channel information from fshape as well as
        # data, thats why we use i+1 (first space reserved for batch) and 
        # ignore last (channel) in data
        for i, j in enumerate(fshape[:-2]):
            begin1 = np.zeros(len(shape), dtype=np.int32)
            size1 = -np.ones(len(shape), dtype=np.int32)
            begin2 = np.zeros(len(shape), dtype=np.int32)
            size2 = -np.ones(len(shape), dtype=np.int32)
            front = (j - 1) // 2
            back = j - 1 - front
            begin1[i + 1] = shape[i + 1] - front
            size1[i + 1] = front
            size2[i + 1] = back
            data = tf.concat([tf.slice(data, begin1, size1), data, tf.slice(data, begin2, size2)], i + 1)
        return data

    def _get_dropconnect(self, shape, rate, name):
        if rate is None:
            return None
        if self.use_bernoulli:
            dc = tf.random_uniform(shape, 0, 1, tf.float32, None, name) < rate
            return tf.cast(dc, tf.float32) / rate
        else:
            return tf.random_normal(shape, 1, tf.sqrt((1 - rate) / rate), tf.float32, None, name)

    def _convolution_x(self, data, filterx, filter_shape=None, strides=None):
        if self.periodicconvolution_x:
            # do padding
            data = self._paddata(data, filterx.get_shape().as_list())
            return tf.nn.convolution(data, filterx, "VALID", strides=strides)
        else:
            return convolution_helper_padding_same(data, filterx, filter_shape, strides)

    def _convolution_h(self, data, filterh, filter_shape=None, strides=None):
        if self.periodicconvolution_h:
            # do padding
            data = self._paddata(data, filterh.get_shape().as_list())
            return tf.nn.convolution(data, filterh, "VALID", strides=strides)
        else:
            return convolution_helper_padding_same(data, filterh, filter_shape, strides)

    def _convlinear(self, args, output_size, bias, bias_start=0.0,
                    scope=None, dropconnectx=None, dropconnecth=None, dropconnectxmatrix=None, dropconnecthmatrix=None,
                    strides=None, orthogonal_init=True, **kw):  # dropconnect and dropout are keep probabilities

        if args is None or (nest.is_sequence(args) and not args):
            raise ValueError("`args` must be specified")

        # Calculate the total size of arguments on dimension 1.
        total_arg_size = 0
        shape = args[1].get_shape().as_list()
        if len(shape) != 2:
            raise ValueError("ConvLinear is expecting 2D arguments: %s" % str(shape))
        if not shape[1]:
            raise ValueError("ConvLinear expects shape[1] of arguments: %s" % str(shape))
        else:
            total_arg_size = shape[1]

        if self.myshapes[1][-1] != total_arg_size:
            logging.getLogger('model').warning('orig_shape does not match.')

        dtype = args[0].dtype

        # Now the computation.
        with vs.variable_scope(scope or "ConvLinear"):
            # reshape to original shape:
            inp = tf.reshape(args[0], self.myshapes[0])
            stat = tf.reshape(args[1], self.myshapes[1])
            # input
            filtershapex = deepcopy(self.filter_size_x)#[filter_size[0] for _ in range(len(orig_shapes[0][1:-1]))]
            #             strides = [1 for i in filtershape]
            filtershapex.append(self.myshapes[0][-1])
            numelem = np.prod(filtershapex)
            filtershapex.append(output_size)
            filterinp = self._get_weights_x(filtershapex, dtype, numelem, "FilterInp")

            if dropconnectx is not None:
                filterinp *= dropconnectxmatrix

            resinp = self._convolution_x(inp, filterinp, filter_shape=filtershapex, strides=strides)
            # state
            filtershapeh = deepcopy(self.filter_size_h)#[filter_size[1] for _ in range(len(orig_shapes[1][1:-1]))]
            filtershapeh.append(self.myshapes[1][-1])
            numelem = np.prod(filtershapeh)
            filtershapeh.append(output_size)

            filterstat = self._get_weights_h(filtershapeh, dtype, numelem, "FilterStat",
                                             orthogonal_init=orthogonal_init)
            if dropconnecth is not None:
                filterstat *= dropconnecthmatrix

            resstat = self._convolution_h(stat, filterstat, filter_shape=filtershapeh)

        # back to orig shape
        resinp = tf.reshape(resinp, (-1, output_size))
        resstat = tf.reshape(resstat, (-1, output_size))

        if bias:
            bias_term = vs.get_variable(
                "Bias", [output_size],
                dtype=dtype,
                initializer=init_ops.constant_initializer(
                    bias_start, dtype=dtype))
            resbias = tf.reshape(bias_term, (-1, output_size))
            return resinp, resstat, resbias
        else:
            return resinp, resstat

    def _get_weights_x(self, filtershape, dtype, _numelem, name):
        fs = np.prod(filtershape[:-2])
        num_output = filtershape[-2]
        num_input = filtershape[-1]

        # depending on the activation function, we initialize our weights differently!
        numelem = (fs * num_output + fs * num_input) / 2
        uniform = False
        if self._activation in [tf.nn.elu, tf.nn.relu]:
            numelem = (fs * num_input) / 2
            uniform = False

        return vs.get_variable(
            name, filtershape, dtype=dtype, initializer=get_modified_xavier_method(numelem, uniform))

    def _get_weights_h(self, filtershape, dtype, numelem, name, orthogonal_init=True):
        if len(filtershape) == 4 and orthogonal_init:
            return vs.get_variable(
                name, filtershape, dtype=dtype,
                initializer=get_orthogonal_block_circulant_initialization())  # initializer=get_modified_xavier_method(numelem,False))
        else:
            fs = np.prod(filtershape[:-2])
            num_output = filtershape[-2]
            num_input = filtershape[-1]
            numelem = (fs * num_output + fs * num_input) / 2
            uniform = False
            if self._activation in [tf.nn.elu, tf.nn.relu]:
                numelem = (fs * num_input) / 2
                uniform = False

            return vs.get_variable(
                name, filtershape, dtype=dtype, initializer=get_modified_xavier_method(numelem, uniform))


class CGRUCell(CRNNCell):
    def __init__(self, *w, **kw):
        self.bnx = argget(kw, "add_x_bn", False)
        self.bnh = argget(kw, "add_h_bn", False)
        self.bna = argget(kw, "add_a_bn", False)
        self.m = argget(kw, "m", None)
        self.istraining = argget(kw, 'istraining', tf.constant(True))
        self.resgrux = argget(kw, "resgrux", False)
        self.resgruh = argget(kw, "resgruh", False)
        self.put_r_back = argget(kw, "put_r_back", False)
        self.regularize_state = argget(kw, 'use_dropconnect_on_state', False)

        super(CGRUCell, self).__init__(*w, **kw)

        filterhshapecandidate = self.filter_size_h + [self._num_units] * 2
        filterhshapegates = deepcopy(filterhshapecandidate)
        filterhshapegates[-1] *= 2

        filterxshapecandidate = self.filter_size_x + [self.myshapes[0][-1], self._num_units]
        filterxshapegates = deepcopy(filterxshapecandidate)
        filterxshapegates[-1] *= 2

        self.dropconnecthmatrixgates = self._get_dropconnect(filterhshapegates, self.dropconnecth, "mydropconnecthgates")
        self.dropconnecthmatrixcandidate = self._get_dropconnect(filterhshapecandidate, self.dropconnecth, "mydropconnecthcandidate")

        self.dropconnectxmatrixgates = self._get_dropconnect(filterxshapegates, self.dropconnectx, "mydropconnectxgates")
        self.dropconnectxmatrixcandidate = self._get_dropconnect(filterxshapecandidate, self.dropconnectx, "mydropconnectxcandidate")

    def __call__(self, inputs, state, scope=None):
        """Gated recurrent unit (GRU) with nunits cells."""
        with vs.variable_scope(scope or type(self).__name__):  # "GRUCell"
            with vs.variable_scope("Gates"):  # Reset gate and update gate.
                # We start with bias of 1.0 to not reset and not update.
                zrx, zrh, zrb = self._convlinear([inputs, state], self._num_units * 2, True, 1.0,
                                                 dropconnectx=self.dropconnectx, dropconnecth=self.dropconnecth,
                                                 dropconnectxmatrix=self.dropconnectxmatrixgates,
                                                 dropconnecthmatrix=self.dropconnecthmatrixgates,
                                                 strides=self.strides, orthogonal_init=False)
            if self.bnx:
                zrx = batch_norm(zrx, "bnx", self.istraining, bias=None, m=self.m)
            if self.bnh:
                zrh = batch_norm(zrh, "bnh", self.istraining, bias=None, m=self.m)
            with vs.variable_scope('resgru'):
                if self.resgrux:
                    ntiles = self._num_units // inputs.get_shape().as_list()[-1]
                    if ntiles * inputs.get_shape().as_list()[-1] != self._num_units:
                        logging.getLogger('model').error(
                            'cant do resgrux here, since {}*{} is smaller than the actual number of outputs. (needs to be multiple){}'
                            .format(ntiles, inputs.get_shape().as_list()[-1], self._num_units))
                    else:
                        zrx = tf.tile(inputs, [1, ntiles * 2]) + zrx
                if self.resgruh:
                    zrh = tf.tile(state, [1, 2]) + zrh
            z, r = tf.split(zrx + zrh + zrb, 2, axis=len(inputs.get_shape()) - 1)
            r, z = self.gate(r), self.gate(z)
            with vs.variable_scope("Candidate"):
                if self.put_r_back:
                    state *= r
                usedx = self.dropconnectx if self.regularize_state else None
                usedh = self.dropconnecth if self.regularize_state else None
                htx, hth, htb = self._convlinear([inputs, state],
                                                 self._num_units, True,
                                                 dropconnectxmatrix=self.dropconnectxmatrixcandidate,
                                                 dropconnecthmatrix=self.dropconnecthmatrixcandidate,
                                                 dropconnectx=usedx, dropconnecth=usedh,
                                                 strides=self.strides)
                if self.put_r_back:
                    htwb = htx + hth
                else:
                    htwb = htx + r * hth
            if self.bna:
                htwb = batch_norm(htwb, "bna", self.istraining, bias=None, m=self.m)

            new_h = z * state + (1 - z) * self._activation(htwb + htb)
        return new_h, new_h