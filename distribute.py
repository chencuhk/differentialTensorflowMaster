#coding=utf-8
import numpy as np
import tensorflow as tf
import time
# Define parameters
FLAGS = tf.app.flags.FLAGS
tf.app.flags.DEFINE_float('learning_rate', 0.00003, 'Initial learning rate.')
tf.app.flags.DEFINE_integer('steps_to_validate', 1000,
                     'Steps to validate and print loss')

# For distributed
tf.app.flags.DEFINE_string("ps_hosts", "",
                           "Comma-separated list of hostname:port pairs")
tf.app.flags.DEFINE_string("worker_hosts", "",
                           "Comma-separated list of hostname:port pairs")
tf.app.flags.DEFINE_string("job_name", "", "One of 'ps', 'worker'")
tf.app.flags.DEFINE_integer("task_index", 0, "Index of task within the job")
tf.app.flags.DEFINE_integer("issync", 0, "Whether to adopt asyn or syn，1 stands for syn，0 is asyn")

# Hyperparameters
learning_rate = FLAGS.learning_rate
steps_to_validate = FLAGS.steps_to_validate

def main(_):
  ps_hosts = FLAGS.ps_hosts.split(",")
  worker_hosts = FLAGS.worker_hosts.split(",")
  cluster = tf.train.ClusterSpec({"ps": ps_hosts, "worker": worker_hosts})
  server = tf.train.Server(cluster,job_name=FLAGS.job_name,task_index=FLAGS.task_index)

  issync = FLAGS.issync
  if FLAGS.job_name == "ps":
    server.join()
  elif FLAGS.job_name == "worker":
    with tf.device(tf.train.replica_device_setter(
                    worker_device="/job:worker/task:%d" % FLAGS.task_index,
                    cluster=cluster)):
      global_step = tf.Variable(0, name='global_step', trainable=False)

      input = tf.placeholder("float")
      label = tf.placeholder("float")

      weight = tf.get_variable("weight", [1], tf.float32, initializer=tf.random_normal_initializer())
      bias  = tf.get_variable("biase", [1], tf.float32, initializer=tf.random_normal_initializer())
      pred = tf.multiply(input, weight) + bias

      loss_value = loss(label, pred)
      optimizer = tf.train.GradientDescentOptimizer(learning_rate)
      #the val list to be handled,this line is to gain the gradients from model
      grads_and_vars = optimizer.compute_gradients(loss_value)
      #simply restrict gradient by l2 norm,further handling methods need to be thought out
      #grads_and_vars = [(tf.clip_by_value(g, -1.0, 1.0), v) for g, v in grads_and_vars]
      grads_and_vars =[(tf.clip_by_norm(g, 1), v) for g, v in grads_and_vars]
      # adding gassian noise to gradients
      grads_and_vars =[(g+np.random.normal(loc=0,scale=4),v) for g, v in grads_and_vars] 
      if issync == 1:
        #caculating decent in syn mode
        rep_op = tf.train.SyncReplicasOptimizer(optimizer,
                                                replicas_to_aggregate=len(
                                                  worker_hosts),
                                                replica_id=FLAGS.task_index,
                                                total_num_replicas=len(
                                                  worker_hosts),
                                                use_locking=True)
        train_op = rep_op.apply_gradients(grads_and_vars,
                                       global_step=global_step)
        init_token_op = rep_op.get_init_tokens_op()
        chief_queue_runner = rep_op.get_chief_queue_runner()
      else:
        #calculating decent for asyn mode
        train_op = optimizer.apply_gradients(grads_and_vars,
                                       global_step=global_step)


      init_op = tf.initialize_all_variables()
      
      saver = tf.train.Saver()
      tf.summary.scalar('cost', loss_value)
      summary_op = tf.summary.merge_all()
 
    sv = tf.train.Supervisor(is_chief=(FLAGS.task_index == 0),
                            logdir="./checkpoint/",
                            init_op=init_op,
                            summary_op=None,
                            saver=saver,
                            global_step=global_step,
                            save_model_secs=60)

    with sv.prepare_or_wait_for_session(server.target) as sess:
      # if it is syn mode
      if FLAGS.task_index == 0 and issync == 1:
        sv.start_queue_runners(sess, [chief_queue_runner])
        sess.run(init_token_op)
      step = 0
      start=time.time()
      while  step < 1000000:
        train_x = np.random.randn(1)
        train_y = 2 * train_x + np.random.randn(1) * 0.33  + 10
        _, loss_v, step = sess.run([train_op, loss_value,global_step], feed_dict={input:train_x, label:train_y})
        if step % steps_to_validate == 0:
          w,b = sess.run([weight,bias])
          print("step: %d, weight: %f, biase: %f, loss: %f" %(step, w, b, loss_v))
    end=time.time()
    print('Running time: %s Seconds'%(end-start))
    sv.stop()

def loss(label, pred):
  return tf.square(label - pred)



if __name__ == "__main__":
  tf.app.run()

















