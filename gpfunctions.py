import numpy as np
import tensorflow as tf


# GP Kernels
def rbf_kernel(np_or_tf, x1,x2,l):
	if np_or_tf == "np": 
		return np.exp(-1.0/l**2*np.sum((np.expand_dims(x1,axis=2) - np.expand_dims(x2,axis=1))**2, axis = 3))
	else:
		return tf.exp(-1.0/l**2*tf.reduce_sum((tf.expand_dims(x1,axis=2) - tf.expand_dims(x2,axis=1))**2, axis = 3))
	
def matern32_kernel(np_or_tf, x1,x2,l,gamma=1.0):
	if np_or_tf == "np": 
		dist = np.sum(np.abs(np.expand_dims(x1,axis=2) - np.expand_dims(x2,axis=1)), axis = 3)
		return (1+gamma*np.sqrt(3)*dist/l)*np.exp(-gamma*np.sqrt(3)*dist/l)
	else:
		dist = tf.reduce_sum(np.abs(tf.expand_dims(x1,axis=2) - tf.expand_dims(x2,axis=1)), axis = 3)
		return (1+gamma*np.sqrt(3.0)*dist/l)*tf.exp(-gamma*np.sqrt(3.0)*dist/l)
		
def matern52_kernel(np_or_tf, x1,x2,l,gamma=1.0):
	if np_or_tf == "np": 
		dist = np.sum(np.abs(np.expand_dims(x1,axis=2) - np.expand_dims(x2,axis=1)), axis = 3)
		return (1+gamma*np.sqrt(5)*dist/l+gamma**2*5/3*(dist/l)**2)*np.exp(-gamma*np.sqrt(5)*dist/l)
	else:
		dist = tf.reduce_sum(np.abs(tf.expand_dims(x1,axis=2) - tf.expand_dims(x2,axis=1)), axis = 3)
		return (1+gamma*np.sqrt(5)*dist/l+gamma**2*5/3*(dist/l)**2)*tf.exp(-gamma*np.sqrt(5)*dist/l)
	
# GP Function
def GP(np_or_tf, X,A,x, l, kernel):
	if np_or_tf == "np": 
		k_xX = kernel(np_or_tf, x,X,l)
		return np.squeeze(np.matmul(k_xX,  A),axis=(2,))
	else:
		k_xX = kernel(np_or_tf, tf.expand_dims(x, axis = 1),X,l)
		return tf.squeeze(tf.matmul(k_xX,  A),axis=(2,))


def normalize(minv, maxv, y):
    return 2*(y-minv)/(maxv-minv)-1.0
	
# Objective Priors
def normalized_gp_function(np_or_tf, X, A, minv, maxv, l, kernel, x):
	return normalize(minv,maxv,GP(np_or_tf, X, A, x, l, kernel))
	
def un_normalized_gp_function(X,A,minv,maxv,l,kernel,x):
    return GP(np_or_tf, X, A, x, l, kernel)
	
def airfoil_prior(np_or_tf, X,A,minv,maxv,l,kernel,x):
	if np_or_tf == "np": 
		minv = np.tanh(1.5*minv+0.3)
		maxv = np.tanh(1.5*maxv+0.3)
		return  normalize(minv,maxv,np.tanh(1.5*(GP(np_or_tf, X,A,x,l,kernel))+0.3))
	else:
		minv = tf.tanh(1.5*minv+0.3)
		maxv = tf.tanh(1.5*maxv+0.3)
		return  normalize(minv,maxv,tf.tanh(1.5*(GP(np_or_tf, X,A,x,l,kernel))+0.3))
	
	

	