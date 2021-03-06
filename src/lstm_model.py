import tensorflow as tf
import numpy as np
import benchmarkfunctions as fun
import utils
import sys
import time

import gpfunctions as gp
import os
import json
import utils
from prettytable import PrettyTable

def get_lstm_weights(n_hidden, forget_bias, dim, scope="rnn_cell"):
    # Create LSTM cell
    cell = tf.contrib.rnn.LSTMCell(num_units = n_hidden, reuse=None, forget_bias = forget_bias)
    cell(tf.zeros([1, dim +1]), (tf.zeros([1, n_hidden]),tf.zeros([1, n_hidden])), scope=scope)
    cell = tf.contrib.rnn.LSTMCell(num_units = n_hidden, reuse=True, forget_bias = forget_bias)

    # Create output weights
    weights = {
        'W_1': tf.Variable(tf.truncated_normal([n_hidden, dim], stddev=0.05)),
        'b_1': tf.Variable(0.1*tf.ones([dim])),
    }

    return cell, weights

def next_sample_point(x,y,state,cell,weights, scope="rnn_cell"):
	h, state = cell(tf.concat([x, y], 1), state, scope=scope)
	x = tf.matmul(h, weights['W_1']) + weights['b_1']
	return x,state

def apply_lstm_model(f, cell, weights, n_steps, dim, n_hidden, batch_size, scope="rnn_cell"):

    x_0 = tf.placeholder(tf.float32, [1,dim])
    x_00 = tf.tile(x_0, [batch_size,1])
    h_0 = tf.zeros([batch_size, n_hidden])
    c_0 = tf.zeros([batch_size, n_hidden])

    state = (c_0, h_0)
    x = x_00
    y = f(x)
    samples_x = [x]
    samples_y = [y]

    for i in range(n_steps):
        x, state = next_sample_point(x,y,state,cell,weights, scope=scope)
		#h, state = cell(tf.concat([x, y], 1), state, scope=scope)
        #x = tf.matmul(h, weights['W_1']) + weights['b_1']
        y = f(x)

        samples_x.append(x)
        samples_y.append(y)

    return samples_x, samples_y, x_0

def build_training_graph(n_bumps, dim, n_hidden, forget_bias, n_steps, l, kernel=gp.rbf_kernel, function=gp.normalized_gp_function, scope="rnn_cell"):
    # Create Model
    Xt = tf.placeholder(tf.float32, [None, n_bumps, dim])
    At = tf.placeholder(tf.float32, [None, n_bumps, 1])
    mint = tf.placeholder(tf.float32, [None, 1])
    maxt = tf.placeholder(tf.float32, [None, 1])

    f = lambda x: function("tf", Xt, At, mint, maxt, l, kernel, x)

    cell, weights = get_lstm_weights(n_hidden, forget_bias, dim, scope=scope)

    samples_x, samples_y, x_0 = apply_lstm_model(f, cell, weights, n_steps, dim, n_hidden, tf.shape(Xt)[0], scope=scope)



    return Xt, At, mint, maxt, samples_x, samples_y, x_0, cell, weights

def get_loss(samples_y, loss_type, samples_x=None):

    n_steps = len(samples_y)

    loss_dict = {
        "MIN" : lambda x : tf.reduce_mean(tf.reduce_min(x, axis = 0)),
        "SUM" : lambda x : tf.reduce_mean(tf.reduce_sum(x, axis = 0)),
        "WSUM" : lambda x : \
            tf.reduce_mean(tf.reduce_sum(tf.multiply(x, np.linspace(1/(n_steps+1),1, n_steps+1)), axis = 0)),
        "OI" : lambda x : \
            tf.reduce_mean( tf.reduce_sum( [tf.minimum(0.0,x[i] -tf.reduce_min(tf.stop_gradient(x[:i]),axis = 0)) for i in range(1,n_steps)], axis = 0)),
        "SUMMIN" : lambda x : tf.reduce_mean(tf.reduce_min(x, axis = 0)) +\
            tf.reduce_mean(tf.reduce_sum(x, axis = 0)) ,\
        'WSUM_EXPO': lambda x: \
             tf.reduce_mean(tf.reduce_sum(tf.multiply(x, np.power(0.5,np.arange(1,n_steps+1)[::-1])), axis = 0)),
		'SUMOI' : lambda x: \
            tf.reduce_mean( tf.reduce_sum( [tf.reduce_min( x[i] - tf.reduce_min(x[:i]), 0  ) for i in range(1, n_steps) ], axis = 0  ), axis=0 ) + \
			tf.reduce_mean(tf.reduce_sum(x, axis = 0)),
		'DIST' : lambda x, y: \
			tf.reduce_mean(tf.reduce_sum([tf.reduce_sum([(1.0)/(0.1+tf.reduce_sum((x[i]-x[j])**2)) \
				for j in range(i)],axis = 0) for i in range(1,n_steps)],axis=0))
    }

    if loss_type=='DIST':
	    loss = loss_dict['DIST'](samples_x, samples_y)
    else:
        loss = loss_dict[loss_type](samples_y)

    return loss

def get_min(samples_y):
    return tf.reduce_mean(tf.reduce_min(samples_y, axis = 0))

def get_train_step(loss, gradient_clipping):
    rate = tf.placeholder(tf.float32, [])

    optimizer = tf.train.AdamOptimizer(learning_rate=rate)
    gvs = optimizer.compute_gradients(loss)
    capped_gvs = [(tf.clip_by_value(grad, -gradient_clipping, gradient_clipping), var) for grad, var in gvs]
    train_step = optimizer.apply_gradients(capped_gvs)

    return train_step, rate

def train_model(sess, placeholders, samples_x, samples_y, epochs, batch_size, data_train, data_test, rate_init, rate_decay, gradient_clipping, \
                loss_type, x_start, max_x_abs_value, log = True):

    print("Build Graph...")
    X_train, A_train, min_train, max_train = data_train
    X_test, A_test, min_test, max_test = data_test
    n_train = X_train.shape[0]

    Xt = placeholders["Xt"]
    At = placeholders["At"]
    mint = placeholders["mint"]
    maxt = placeholders["maxt"]
    x_0 = placeholders["x0"]

    loss = get_loss(samples_y, loss_type, samples_x)

    regularizer = 100*(tf.reduce_mean(tf.maximum(max_x_abs_value,tf.abs(samples_x)))-max_x_abs_value )

    loss = loss + regularizer

    f_min = get_min(samples_y)

    train_step, train_rate = get_train_step(loss, gradient_clipping)

    if log:
        train_loss_list = []
        test_loss_list = []
        train_fmin_list = []
        test_fmin_list = []

    learning_rate = rate_init

    sess.run(tf.global_variables_initializer())
    for ep in range(epochs):
        learning_rate *= rate_decay

        for batch in range(n_train//batch_size):
            X_batch = X_train[batch*batch_size:(batch+1)*batch_size]
            A_batch = A_train[batch*batch_size:(batch+1)*batch_size]
            min_batch = min_train[batch*batch_size:(batch+1)*batch_size]
            max_batch = max_train[batch*batch_size:(batch+1)*batch_size]

            sess.run([train_step],\
                     feed_dict={Xt: X_batch, At: A_batch, mint: min_batch, maxt: max_batch, x_0: x_start,\
                                train_rate: learning_rate})

        if log:
            train_loss, train_fmin = sess.run([loss, f_min], feed_dict=\
                                              {Xt: X_train, At: A_train, mint: min_train, maxt: max_train, x_0: x_start})
            test_loss, test_fmin = sess.run([loss, f_min], feed_dict=\
                                              {Xt: X_test, At: A_test, mint: min_test, maxt: max_test, x_0:x_start})
            train_loss_list += [train_loss]
            test_loss_list += [test_loss]
            train_fmin_list += [train_fmin]
            test_fmin_list += [test_fmin]

        if log and (ep < 10 or ep % (epochs // 10) == 0 or ep == epochs-1):
            print("Ep: " +"{:4}".format(ep)+" | TrainLoss: "+"{: .3f}".format(train_loss)
                  +" | TrainMin: "+ "{: .3f}".format(train_fmin)+ " | TestLoss: "+
                  "{: .3f}".format(test_loss)+" | TestMin: "+ "{: .3f}".format(test_fmin))

    print("Done.")
    if log:
        return (train_loss_list, test_loss_list, train_fmin_list, test_fmin_list)
    return None

def train(dim, kernel = "rbf", n_steps = 20, learning_rate_init=0.001, learning_rate_final=0.0001, epochs=1000, n_hidden = 50, batch_size = 160, loss_function='WSUM', logger=sys.stdout, close_session=True, n_bumps=6, forget_bias=5.0, gradient_clipping=5.0, save_model_path=None, max_x_abs_value=1.0, starting_point=[-1,-1]):
    tf.set_random_seed(1)

    learning_rate_decay_rate = (learning_rate_final/learning_rate_init) ** (1.0 / (epochs-1) )

    # declare utils
    debug = lambda x : (print(x, file=logger), logger.flush())

    # load data
    X_train, A_train, min_train, max_train = utils.loadData(dim, "training", kernel = kernel)
    X_test, A_test, min_test, max_test = utils.loadData(dim, "testing", kernel = kernel)

    l = 2/n_bumps*np.sqrt(dim)

    scope = 'rnn-cell-%dd-%d' % (dim,int(time.time()))

    kernel_func = None
    if kernel is "rbf":
        kernel_func = gp.rbf_kernel
    elif kernel is "matern32":
        kernel_func = gp.matern32_kernel
    elif kernel is "matern52":
        kernel_func = gp.matern52_kernel

    Xt, At, mint, maxt, samples_x, samples_y, x_0, cell, weights = \
        build_training_graph(n_bumps, dim, n_hidden, forget_bias, n_steps, l, kernel=kernel_func, scope=scope)

    loss = get_loss(samples_y, loss_function)

    regularizer = 100*(tf.reduce_mean(tf.maximum(max_x_abs_value,tf.abs(samples_x)))-max_x_abs_value )

    loss = loss + regularizer

    f_min = get_min(samples_y)

    train_step, train_rate = get_train_step(loss, gradient_clipping)

    sess = tf.Session()
    sess.run(tf.global_variables_initializer())

    # Train the Network
    debug("------------------------------------------------------------------------------------")
    debug("%-30s: %d" % ("Function Dimension", dim) )
    debug("%-30s: %s" % ("RNN Scope", scope) )
    debug("%-30s: %d" % ("Number of Training Samples", len(X_train)) )
    debug("%-30s: %d" % ("Number of Test Samples", len(X_test)) )
    debug("%-30s: %s" % ("Loss", loss_function) )
    debug("%-30s: %d" % ("Batch size", batch_size) )
    debug("%-30s: %d" % ("Number of hidden Units", n_hidden) )
    debug("%-30s: %d" % ("Sequence length", n_steps) )
    debug("%-30s: %d" % ("Epochs",epochs) )
    debug("%-30s: %.5f" % ("Learning rate init", learning_rate_init) )
    debug("%-30s: %.5f" % ("Learning rate decay", learning_rate_decay_rate) )
    debug("%-30s: %.5f" % ("Learning rate final", learning_rate_final) )
    debug("------------------------------------------------------------------------------------")

    learning_rate = learning_rate_init

    starting_point = np.array(starting_point).reshape(1,dim)
    for ep in range(epochs):
        learning_rate = learning_rate * learning_rate_decay_rate

        for batch in range(len(X_train)//batch_size):
            X_batch = X_train[batch*batch_size:(batch+1)*batch_size]
            A_batch = A_train[batch*batch_size:(batch+1)*batch_size]
            min_batch = min_train[batch*batch_size:(batch+1)*batch_size]
            max_batch = max_train[batch*batch_size:(batch+1)*batch_size]

            sess.run([train_step], feed_dict={Xt: X_batch, At: A_batch, mint: min_batch, maxt: max_batch, train_rate: learning_rate, x_0: starting_point })

        if ep < 10 or ep % (epochs // 10) == 0 or ep == epochs-1:
            train_loss, train_fmin = sess.run([loss, f_min], feed_dict=\
                                              {Xt: X_train, At: A_train, mint: min_train, maxt: max_train, x_0: starting_point})
            test_loss, test_fmin = sess.run([loss, f_min], feed_dict=\
                                            {Xt: X_test, At: A_test, mint: min_test, maxt: max_test, x_0: starting_point})
            msg = "Ep: %4d | TrainLoss : %.3f | TrainMin: %.3f | TestLoss: %.3f | TestMin: %.3f" % (ep, train_loss, train_fmin, test_loss, test_fmin)
            debug(msg)

    debug('Last output: %s' % msg)
    if save_model_path:
        # TODO : Save network-params.json

        dir_path = "%s/%s" %( save_model_path, scope )
        os.makedirs(dir_path)
        checkpoint_file = "%s/model" % (dir_path)

        debug('Save model to %s' % checkpoint_file)
        saver = tf.train.Saver()
        saver.save(sess, checkpoint_file)

        network_params = {
            'n_hidden': n_hidden,
            'n_bumps': n_bumps,
            'forget_bias': forget_bias,
            'n_steps': n_steps,
            'scope': scope,
            'dim': dim,
            'gp_length': l,
            'loss_function': loss_function,
            'learning_rate_init': learning_rate_init,
            'learning_rate_final': learning_rate_final,
            'epochs': epochs
        }
        with open( '%s/network-params.json' % dir_path, 'w') as f:
            json.dump(network_params, f)

    sess.close()

def get_samples(sess, placeholders, samples_x, samples_y, data, x_start):
    t_start = time.time()

    X, A, minv, maxv = data
    n_train = X.shape[0]

    n = X.shape[0]
    dim = X.shape[-1]

    Xt = placeholders["Xt"]
    At = placeholders["At"]
    mint = placeholders["mint"]
    maxt = placeholders["maxt"]
    x_0 = placeholders["x0"]

    # Extract Samples
    samples_v_x, samples_v_y = sess.run([samples_x, samples_y], feed_dict={Xt: X, At: A, mint: minv, maxt: maxv, x_0: x_start})
    samples_v_x = np.array(samples_v_x).reshape(-1,n, dim).transpose((1,0,2))
    samples_v_y = np.array(samples_v_y).reshape(-1,n).T

    print(time.time()-t_start)

    return samples_v_x, samples_v_y


# deprecated!!! use sk_optimization.get_samples_sk instead!
def get_random_baseline(X_test, A_test, min_test, max_test, l, kernel, function, n_test,n_steps,dim):

	random_samples = function("np", X_test, A_test, min_test, max_test, l, kernel,\
			 np.random.uniform(low=-1.0,high=1.0,size=[n_test,n_steps,dim]))

	samples_sorted = [np.min(random_samples[:,:i],axis=1) for i in range(1,n_steps+1)]
	samples_sorted = np.mean(np.array(samples_sorted),axis = 1)

	baseline = np.mean(np.min(random_samples,axis=1))

	#print("deprecated!!! use sk_optimization.get_samples_sk instead!")
	return random_samples

def get_benchmark_samples(sess, f, cell, weights, dim, n_hidden, n_steps, x_start, scope="rnn_cell"):
    samples_x, samples_y, x_0 = apply_lstm_model(f, cell, weights, n_steps, dim, n_hidden, 1, scope="rnn_cell")

    samples_benchmark_x, samples_benchmark_y = sess.run([samples_x, samples_y], feed_dict={x_0: x_start})
    samples_benchmark_x = np.array(samples_benchmark_x).reshape(-1,1, dim).transpose((1,0,2))
    samples_benchmark_y = np.array(samples_benchmark_y).reshape(-1,1).T

    return samples_benchmark_x, samples_benchmark_y

def load_model_params(model, debug=False):
    tf.reset_default_graph()
    model_path = '%s/trained_models/%s' % (utils.get_base_dir(), model)

    with open('%s/network-params.json' % model_path ) as jsonfile:
        model_params = json.load(jsonfile)

    model_params['model_path'] = '%s/model' % model_path

    keys = list(model_params.keys())
    keys.sort()

    table = PrettyTable()
    table.field_names = ["Parameter", "Value"]

    for k in keys:
        table.add_row([k, model_params[k]])

    table.align = 'l'

    if debug:
        print(model_path)
        print('Load %s model' % model )
        print(table)

    # sess = tf.session()

    # params_dict = {
    #     'n_bumps': model_params['n_bumps'],
    #     'dim' : model_params['dim'],
    #     'n_hidden': model_params['n_hidden'],
    #     'forget_bias': model_params['forget_bias'],
    #     'n_steps': model_params['n_steps'],
    #     'l': model_params['gp_length'],
    #     'scope': model_params['scope']
    # }

    # build_training_graph(**params_dict)

    # saver = tf.train.Saver()
    # saver.restore(sess, '%s/model' % model_path)

    return model_params

def generate_sample_sequence(sess, model_params, x0, steps, obj_func):
    h_0 = tf.zeros([1, model_params['n_hidden']])
    c_0 = tf.zeros([1, model_params['n_hidden']])

    x = tf.constant(x0, dtype=tf.float32)
    state = (c_0, h_0)

    y0 = obj_func(x0)
    y = tf.constant(y0, dtype=tf.float32)

    samples_x = [x0]
    samples_y = [y0]

    for i in range(steps):
        x, state = next_sample_point(x,y,state, model_params['_cell'], model_params['_weights'], scope=model_params['scope'])
        x_np = sess.run(x)
        y_np = obj_func(x_np)
        y = tf.constant(y_np, dtype=tf.float32)

        samples_x += [x_np]
        samples_y += [y_np]

    return samples_x, samples_y

def load_trained_model(model, debug=False):
    model_params = load_model_params(model, debug=True)
    tf.reset_default_graph()

    sess = tf.Session()

    lstm_params = {
        'dim' : model_params['dim'],
        'n_hidden': model_params['n_hidden'],
        'forget_bias': model_params['forget_bias'],
        'scope': model_params['scope']
    }
    cell, weights = get_lstm_weights(**lstm_params)

    saver = tf.train.Saver()
    saver.restore(sess, model_params['model_path'])

    model_params['_cell'] = cell
    model_params['_weights'] = weights

    return sess, model_params

if __name__ == "__main__":
    print("run as main")
    dim = 2
    f = open('something-%d.txt' %dim, 'w')
    train(dim, epochs=2, save_model_path="./trained_models", loss_function="OI_UPDATED")




