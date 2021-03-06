# -*- coding:utf-8 -*-
__author__ = 'Randolph'

import tensorflow as tf


class TextFAST(object):
    """A FASTTEXT for text classification."""

    def __init__(
            self, sequence_length, vocab_size, embedding_type, embedding_size, num_classes,
             l2_reg_lambda=0.0, pretrained_embedding=None):

        # Placeholders for input, output, dropout_prob and training_tag
        self.input_x_front = tf.placeholder(tf.int32, [None, sequence_length], name="input_x_front")
        self.input_x_behind = tf.placeholder(tf.int32, [None, sequence_length], name="input_x_behind")
        self.input_y = tf.placeholder(tf.float32, [None, num_classes], name="input_y")
        self.dropout_keep_prob = tf.placeholder(tf.float32, name="dropout_keep_prob")
        self.is_training = tf.placeholder(tf.bool, name="is_training")

        self.global_step = tf.Variable(0, trainable=False, name="Global_Step")

        def _linear(input_, output_size, initializer=None, scope="SimpleLinear"):
            """
            Linear map: output[k] = sum_i(Matrix[k, i] * args[i] ) + Bias[k].

            Args:
                input_: a tensor or a list of 2D, batch x n, Tensors.
                output_size: int, second dimension of W[i].
                initializer: The initializer.
                scope: VariableScope for the created subgraph; defaults to "SimpleLinear".
            Returns:
                A 2D Tensor with shape [batch x output_size] equal to
                sum_i(args[i] * W[i]), where W[i]s are newly created matrices.
            Raises:
                ValueError: if some of the arguments has unspecified or wrong shape.
            """

            shape = input_.get_shape().as_list()
            if len(shape) != 2:
                raise ValueError("Linear is expecting 2D arguments: {0}".format(str(shape)))
            if not shape[1]:
                raise ValueError("Linear expects shape[1] of arguments: {0}".format(str(shape)))
            input_size = shape[1]

            # Now the computation.
            with tf.variable_scope(scope):
                W = tf.get_variable("W", [input_size, output_size], dtype=input_.dtype)
                b = tf.get_variable("b", [output_size], dtype=input_.dtype, initializer=initializer)

            return tf.nn.xw_plus_b(input_, W, b)

        def _highway_layer(input_, size, num_layers=1, bias=-2.0):
            """
            Highway Network (cf. http://arxiv.org/abs/1505.00387).
            t = sigmoid(Wx + b); h = relu(W'x + b')
            z = t * h + (1 - t) * x
            where t is transform gate, and (1 - t) is carry gate.
            """

            for idx in range(num_layers):
                h = tf.nn.relu(_linear(input_, size, scope=("highway_h_{0}".format(idx))))
                t = tf.sigmoid(_linear(input_, size, initializer=tf.constant_initializer(bias),
                                       scope=("highway_t_{0}".format(idx))))
                output = t * h + (1. - t) * input_
                input_ = output

            return output

        # Embedding Layer
        with tf.device("/cpu:0"), tf.name_scope("embedding"):
            # Use random generated the word vector by default
            # Can also be obtained through our own word vectors trained by our corpus
            if pretrained_embedding is None:
                self.embedding = tf.Variable(tf.random_uniform([vocab_size, embedding_size], minval=-1.0, maxval=1.0,
                                                               dtype=tf.float32), trainable=True, name="embedding")
            else:
                if embedding_type == 0:
                    self.embedding = tf.constant(pretrained_embedding, dtype=tf.float32, name="embedding")
                if embedding_type == 1:
                    self.embedding = tf.Variable(pretrained_embedding, trainable=True,
                                                 dtype=tf.float32, name="embedding")
            self.embedded_sentence_front = tf.nn.embedding_lookup(self.embedding, self.input_x_front)
            self.embedded_sentence_behind = tf.nn.embedding_lookup(self.embedding, self.input_x_behind)

        # Combine two sentence embedding representation
        self.embedded_sentence_combine = tf.concat([self.embedded_sentence_front,
                                                    self.embedded_sentence_behind], axis=2)

        # Average Vectors
        self.embedded_sentence_average = tf.reduce_mean(self.embedded_sentence_combine, axis=1)

        # Highway Layer
        with tf.name_scope("highway"):
            self.highway = _highway_layer(self.embedded_sentence_average,
                                          self.embedded_sentence_average.get_shape()[1], num_layers=1, bias=0)

        # Add dropout
        with tf.name_scope("dropout"):
            self.h_drop = tf.nn.dropout(self.highway, self.dropout_keep_prob)

        # Final scores and predictions
        with tf.name_scope("output"):
            W = tf.Variable(tf.truncated_normal(shape=[embedding_size * 2, num_classes],
                                                stddev=0.1, dtype=tf.float32), name="W")
            b = tf.Variable(tf.constant(value=0.1, shape=[num_classes], dtype=tf.float32), name="b")
            self.logits = tf.nn.xw_plus_b(self.h_drop, W, b, name="logits")
            self.softmax_scores = tf.nn.softmax(self.logits, name="softmax_scores")
            self.topKPreds = tf.nn.top_k(self.softmax_scores, k=1, sorted=True, name="topKPreds")

        # Calculate mean cross-entropy loss, L2 loss
        with tf.name_scope("loss"):
            losses = tf.nn.softmax_cross_entropy_with_logits_v2(labels=self.input_y, logits=self.logits)
            losses = tf.reduce_mean(losses, name="softmax_losses")
            l2_losses = tf.add_n([tf.nn.l2_loss(tf.cast(v, tf.float32)) for v in tf.trainable_variables()],
                                 name="l2_losses") * l2_reg_lambda
            self.loss = tf.add(losses, l2_losses, name="loss")