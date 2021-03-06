Model (Tensorflow backend)
==========================

These are optional controllable parameters for the CGRUnits inside a MDGRU block.

**periodic convolution on input x (dtype=bool)**
::

    --periodic_convolution_x False

**periodic convolution on input h (dtype=bool)**
::

    --periodic_convolution_h False
    
**use Bernoulli distribution (insted of Gaussian) for dropconnect (dtype=bool)**
::

    --use_bernoulli False
    
**stride (dtype=int)**
::

    --strides None

**use dropconnect on input x (dtype=bool)**
::

    --use_dropconnect_x True
    
**use dropconnect on input h (dtype=bool)**
::

    --use_dropconnect_h True
    
**don't use average pooling (dtype=bool)**
::
    
    --no_avg_pooling True
    
**filter size for input x (dtype=int)**
::

    --filter_size_x 7
    
**filter size for input h (dtype=int)**
::

    --filter_size_h 7
    
**use static RNN (dtype=bool)**
::

    --use_static_rnn False

    
**add batch normalization at the input x in gate (dtype=bool)**
::

    --add_x_bn False
    
**add batch normalization at the input h in candidate (dtype=bool)**
::

    --add_h_bn False
    
**add batch normalization at the candidates input and state (dtype=bool)**
::

    --add_e_bn False
    
**add residual learning to the input x of each cgru (dtype=bool)**
::

    --resgrux False
    
**add residual learning to the input h of each cgru (dtype=bool)**
::

    --resgruh False
    
**move the reset gate to the location the original GRU applies it at (dtype=bool)**
::

    --put_r_back False
    
**apply dropconnect on the candidate weights as well (dtype=bool)**
::

    --use_dropconnect_on_state False

Subpackages
-----------

.. toctree::

    mdgru.model.crnn
    mdgru.model.mdrnn


MDGRUClassification
------------------------------------------

.. automodule:: mdgru.model.mdgru_classification
    :members:
    :undoc-members:
    :show-inheritance:


Module contents
---------------

.. automodule:: mdgru.model
    :members:
    :undoc-members:
    :show-inheritance:
