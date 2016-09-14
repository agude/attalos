import os

import tensorflow as tf
from enum import Enum

# Attalos Imports
import attalos.util.log.log as l
from attalos.util.wordvectors.glove import GloveWrapper
from attalos.util.wordvectors.w2v import W2VWrapper

from attalos.dataset.dataset import Dataset
from attalos.evaluation.evaluation import Evaluation

from attalos.imgtxt_algorithms.approaches.multihot import MultihotModel
from attalos.imgtxt_algorithms.approaches.naivesum import NaiveSumModel
from attalos.imgtxt_algorithms.approaches.wdv import WDVModel
from attalos.imgtxt_algorithms.approaches.negsampling import NegSamplingModel

logger = l.getLogger(__name__)

class WordVectorTypes(Enum):
    w2v = 1
    glove = 2

class ModelTypes(Enum):
    multihot = MultihotModel
    naivesum = NaiveSumModel
    wdv = WDVModel
    negsamp = NegSamplingModel

def train_batch(sess, model, batch_data):
    """
    Given a Tensorflow session, train the provided model on a single batch.

    Args:
        sess: a Tensorflow session
        model: an Attalos model
        batch_data: a batch generated by model.to_batches

    Returns:
        Training loss for this batch.
    """
    fetches, feed_dict = batch_data
    fetches = model.fit(sess, fetches, feed_dict)
    return fetches

def train_epoch(sess, model, train_dataset, batch_size):
    """
    Given a Tensorflow session, train the provided model for a single epoch over train_dataset using batches of size batch_size.

    Args:
        sess: a Tensorflow session
        model: an Attalos model
        train_dataset: an Attalos dataset
        batch_size: int representing batch size

    Returns:
        Average training loss for this epoch.
    """
    training_losses = []
    for cur_batch_num, batch_data in enumerate(model.iter_batches(train_dataset, batch_size)):
        fetches = train_batch(sess, model, batch_data)
        training_loss = model.get_training_loss(fetches)
        training_losses.append(training_loss)
    avg_training_loss = sum(training_losses) / float(len(training_losses))
    return avg_training_loss

def train(sess, model, num_epochs, train_dataset, batch_size, epoch_verbosity=10, mid_eval=None):
    """
    Given a Tensorflow session, train the provided model for num_epochs over train_dataset using batch_size with the provided epoch_verbosity rate.

    Args:
        sess: a Tensorflow session
        model: an Attalos model
        num_epochs: int representing number of epochs to train for
        train_dataset: an Attalos dataset
        batch_size: int representing batch size
        epoch_verbosity: int representing how often to print average training loss for an epoch

    Returns:
        A list of average training losses, with frequency dictated by epoch_verbosity.
    """
    avg_training_losses = []
    for cur_epoch in xrange(num_epochs):
        verbose = cur_epoch % epoch_verbosity == 0
        avg_training_loss = train_epoch(sess, model, train_dataset, batch_size)
        if verbose:
            logger.info("Finished epoch %s. (Avg. training loss: %s)" % (cur_epoch, avg_training_loss))
            avg_training_losses.append(avg_training_loss)
            if mid_eval is not None:
                fetches, feed_dict, truth = mid_eval
                evaluate(sess, model, fetches, feed_dict, truth)

def evaluate(sess, model, fetches, feed_dict, truth):
    predictions = model.predict(sess, fetches, feed_dict)
    predictions = model.post_predict(predictions)
    evaluator = Evaluation(truth, predictions, k=5)
    logger.info("Evaluation (precision, recall, f1): %s" % evaluator.evaluate())

def load_wv_model(word_vector_file, word_vector_type):
    if word_vector_type == WordVectorTypes.glove.name:
        from glove import Glove
        glove_model = Glove.load_stanford(word_vector_file)
        wv_model = GloveWrapper(glove_model)
    else: #args.word_vector_type == WordVectorTypes.w2v.name:
        import word2vec
        w2v_model = word2vec.load(word_vector_file)
        wv_model = W2VWrapper(w2v_model)
    return wv_model

def convert_args_and_call_model(args):
    logger.info("Parsing train and test datasets.")
    train_dataset = Dataset(args.image_feature_file_train, args.text_feature_file_train, load_image_feats_in_mem=args.in_memory)
    test_dataset = Dataset(args.image_feature_file_test, args.text_feature_file_test)

    logger.info("Reading word vectors from file.")
    wv_model = load_wv_model(args.word_vector_file, args.word_vector_type)

    with tf.Graph().as_default():
        model_cls = ModelTypes[args.model_type].value
        logger.info("Selecting model class: %s" % model_cls.__name__)
        datasets = [train_dataset] if args.cross_eval else [train_dataset, test_dataset]
        model = model_cls(wv_model, datasets, **vars(args))

        logger.info("Preparing test_dataset.")
        fetches, feed_dict, truth = model.prep_predict(test_dataset)

        config = tf.ConfigProto()
        config.gpu_options.allow_growth = True

        with tf.Session(config=config) as sess:
            model.initialize_model(sess)
            if args.model_input_path:
                model.load(sess, args.model_input_path)
            logger.info("Starting training phase.")
            mid_eval = (fetches, feed_dict, truth) if args.verbose_eval else None
            avg_training_losses = train(sess, model, args.num_epochs, train_dataset, args.batch_size, args.epoch_verbosity, mid_eval=mid_eval)
            if args.model_output_path:
                model.save(sess, args.model_output_path)

            logger.info("Starting evaluation phase.")
            evaluate(sess, model, fetches, feed_dict, truth)

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Two layer linear regression')
    parser.add_argument("image_feature_file_train",
                        type=str,
                        help="Image Feature file for the training set")
    parser.add_argument("text_feature_file_train",
                        type=str,
                        help="Text Feature file for the training set")
    parser.add_argument("image_feature_file_test",
                        type=str,
                        help="Image Feature file for the test set")
    parser.add_argument("text_feature_file_test",
                        type=str,
                        help="Text Feature file for the test set")
    parser.add_argument("word_vector_file",
                        type=str,
                        help="Text file containing the word vectors")

    # Optional Args
    parser.add_argument("--learning_rate",
                        type=float,
                        default=0.001,
                        help="Learning Rate")
    parser.add_argument("--num_epochs",
                        type=int,
                        default=200,
                        help="Number of epochs to run for")
    parser.add_argument("--batch_size",
                        type=int,
                        default=128,
                        help="Batch size to use for training")
    #parser.add_argument("--network",
    #                    type=str,
    #                    default="200,200",
    #                    help="Define a neural network as comma separated layer sizes")
    parser.add_argument("--model_type",
                        type=str,
                        default="multihot",
                        choices=['multihot', 'naivesum', 'wdv', 'negsamp'],
                        help="Loss function to use for training")
    parser.add_argument("--in_memory",
                        action='store_true',
                        default="store_false",
                        help="Load training image features into memory for faster training")
    parser.add_argument("--model_input_path",
                        type=str,
                        default=None,
                        help="Model input path (to continue training)")
    parser.add_argument("--model_output_path",
                        type=str,
                        default=None,
                        help="Model output path (to save training)")

    # new args
    parser.add_argument("--hidden_units",
                        type=str,
                        default="200,200",
                        help="Define a neural network as comma separated layer sizes")
    parser.add_argument("--cross_eval",
                        action="store_true",
                        default=False,
                        help="Use if test dataset is different from training dataset")
    parser.add_argument("--word_vector_type",
                        type=str,
                        choices=[t.name for t in WordVectorTypes],
                        help="Format of word_vector_file")
    parser.add_argument("--epoch_verbosity",
                        type=int,
                        default=10,
                        help="Epoch verbosity rate")
    parser.add_argument("--verbose_eval",
                        action="store_true",
                        default=False,
                        help="Use to run evaluation against test data every epoch_verbosity")
    parser.add_argument("--optim_words",
                        action="store_true",
                        default=False,
                        help="If using negsampling model_type, use to jointly optimize words")

    args = parser.parse_args()

    try:
        # Sacred Imports
        from sacred import Experiment
        from sacred.observers import MongoObserver

        from sacred.initialize import Scaffold

        # Monkey patch to avoid having to declare all our variables
        def noop(item):
            pass

        Scaffold._warn_about_suspicious_changes = noop

        ex = Experiment('Attalos')
        ex.observers.append(MongoObserver.create(url=os.environ['MONGO_DB_URI'],
                                                 db_name='attalos_experiment'))
        ex.main(lambda: convert_args_and_call_model(args))
        ex.run(config_updates=args.__dict__)
    except ImportError:
        # We don't have sacred, just run the script
        convert_args_and_call_model(args)


if __name__ == '__main__':
    main()