import os
import csv
import uuid
import glob
import shutil
import tempfile

from pandas import DataFrame

from . import wrapper
from wrapper import constants as const
from . import master_component as mc

from .batches_utils import DICTIONARY_NAME
from .regularizers import Regularizers
from .scores import Scores, TopicMassPhiScore  # temp
from . import score_tracker

SCORE_TRACKER = {
    const.ScoreConfig_Type_SparsityPhi: score_tracker.SparsityPhiScoreTracker,
    const.ScoreConfig_Type_SparsityTheta: score_tracker.SparsityThetaScoreTracker,
    const.ScoreConfig_Type_Perplexity: score_tracker.PerplexityScoreTracker,
    const.ScoreConfig_Type_ThetaSnippet: score_tracker.ThetaSnippetScoreTracker,
    const.ScoreConfig_Type_ItemsProcessed: score_tracker.ItemsProcessedScoreTracker,
    const.ScoreConfig_Type_TopTokens: score_tracker.TopTokensScoreTracker,
    const.ScoreConfig_Type_TopicKernel: score_tracker.TopicKernelScoreTracker,
    const.ScoreConfig_Type_TopicMassPhi: score_tracker.TopicMassPhiScoreTracker,
    const.ScoreConfig_Type_ClassPrecision: score_tracker.ClassPrecisionScoreTracker,
}


def _topic_selection_regularizer_func_1(self, topic_selection_regularizer_name, config, name):
    if str(config.__class__.__name__) == 'TopicSelectionThetaRegularizer':
        topic_selection_regularizer_name.append(name)
        if self._internal_topic_mass_score_name is None:
            self._internal_topic_mass_score_name = 'ITMScore_{}'.format(str(uuid.uuid4()))
            self.scores.add(TopicMassPhiScore(name=self._internal_topic_mass_score_name,
                                              class_id='@default_class'))  # ugly hack!


def _topic_selection_regularizer_func_2(self, topic_selection_regularizer_name):
    if len(topic_selection_regularizer_name):
        n_t = [0] * self.num_topics
        if not self._synchronizations_processed:
            phi = self.get_phi(class_ids=['@default_class'])  # ugly hack!
            n_t = list(phi.sum(axis=0))
        else:
            for i, n in enumerate(self.topic_names):
                n_t[i] = self.score_tracker[
                           self._internal_topic_mass_score_name].last_topic_info[n].topic_mass

        n = sum(n_t)
        for name in topic_selection_regularizer_name:
            config = self.regularizers[name]._config_message()
            config.CopyFrom(self.regularizers[name].config)
            config.ClearField('topic_value')
            for value in [n / (e * self.num_topics) if e > 0.0 else 0.0 for e in n_t]:
                config.topic_value.append(value)
            self.regularizers[name].config = config


class ARTM(object):
    """ARTM represents a topic model (public class)

    Args:
      num_processors (int): how many threads will be used for model training,
      if not specified then number of threads will be detected by the lib
      topic_names (list of str): names of topics in model, if not specified will be
      auto-generated by lib according to num_topics
      num_topics (int): number of topics in model (is used if topic_names
      not specified), default=10
      class_ids (dict): list of class_ids and their weights to be used in model,
      key --- class_id, value --- weight, if not specified then all class_ids
      will be used
      cache_theta (bool): save or not the Theta matrix in model. Necessary
      if ARTM.get_theta() usage expects, default=True
      scores(list): list of scores (objects of artm.***Score classes), default=None
      regularizers(list): list with regularizers (objects of
      artm.***Regularizer classes), default=None
      theta_columns_naming (string): either 'id' or 'title',
      determines how to name columns (documents) in theta dataframe, default='id'

    Important public fields:
      regularizers: contains dict of regularizers, included into model
      scores: contains dict of scores, included into model
      score_tracker: contains dict of scoring results;
      key --- score name, value --- ScoreTracker object, which contains info about
      values of score on each synchronization in list

    NOTE:
      - Here and anywhere in BigARTM empty topic_names or class_ids means that
      model (or regularizer, or score) should use all topics or class_ids.
      - If some fields of regularizers or scores are not defined by
      user --- internal lib defaults would be used.
      - If field 'topic_names' is None, it will be generated by BigARTM and will
      be available using ARTM.topic_names().
    """

    # ========== CONSTRUCTOR ==========
    def __init__(self, num_processors=0, topic_names=None, num_topics=10, class_ids=None,
                 cache_theta=True, scores=None, regularizers=None, theta_columns_naming='id'):
        self._num_processors = 0
        self._num_topics = 10
        self._cache_theta = True
        self._theta_columns_naming = 'id'

        if topic_names is None or not topic_names:
            self._topic_names = []
            if num_topics > 0:
                self._num_topics = num_topics
        else:
            self._topic_names = topic_names
            self._num_topics = len(topic_names)

        if class_ids is None:
            self._class_ids = {}
        elif len(class_ids) > 0:
            self._class_ids = class_ids

        if num_processors > 0:
            self._num_processors = num_processors

        if isinstance(cache_theta, bool):
            self._cache_theta = cache_theta

        if theta_columns_naming in ['id', 'title']:
            self._theta_columns_naming = theta_columns_naming

        self._lib = wrapper.LibArtm()
        self._master = mc.MasterComponent(self._lib,
                                          num_processors=self._num_processors,
                                          cache_theta=self._cache_theta)

        self._model_pwt = 'pwt'
        self._model_nwt = 'nwt'
        self._model_rwt = 'rwt'

        self._regularizers = Regularizers(self._master)
        self._scores = Scores(self._master, self._model_pwt, self._model_nwt, self._model_rwt)

        # add scores and regularizers if necessary
        if scores is not None:
            for score in scores:
                self._scores.add(score)
        if regularizers is not None:
            for regularizer in regularizers:
                self._regularizers.add(regularizer)

        self._score_tracker = {}
        self._synchronizations_processed = 0
        self._initialized = False
        self._phi_cached = None  # This field will be set during .phi_ call
        self._phi_synchronization = -1

        # temp code for easy using of TopicSelectionThetaRegularizer from Python
        self._internal_topic_mass_score_name = None

    def __enter__(self):
        return self

    def dispose(self):
        if self._master is not None:
            self._lib.ArtmDisposeMasterComponent(self.master.master_id)
            self._master = None

    def __exit__(self, exc_type, exc_value, traceback):
        self.dispose()

    def __del__(self):
        self.dispose()

    # ========== PROPERTIES ==========
    @property
    def num_processors(self):
        return self._num_processors

    @property
    def cache_theta(self):
        return self._cache_theta

    @property
    def theta_columns_naming(self):
        return self._theta_columns_naming

    @property
    def num_topics(self):
        return self._num_topics

    @property
    def topic_names(self):
        return self._topic_names

    @property
    def class_ids(self):
        return self._class_ids

    @property
    def regularizers(self):
        return self._regularizers

    @property
    def scores(self):
        return self._scores

    @property
    def score_tracker(self):
        return self._score_tracker

    @property
    def master(self):
        return self._master

    @property
    def model_pwt(self):
        return self._model_pwt

    @property
    def model_nwt(self):
        return self._model_nwt

    @property
    def model_rwt(self):
        return self._model_rwt

    @property
    def num_phi_updates(self):
        return self._synchronizations_processed

    @property
    def phi_(self):
        if (self._phi_cached is None or
                self._phi_synchronization != self._synchronizations_processed):
            self._phi_cached = self.get_phi()
            self._phi_synchronization = self._synchronizations_processed
        return self._phi_cached

    @property
    def info(self):
        return self.master.get_info()

    # ========== SETTERS ==========
    @num_processors.setter
    def num_processors(self, num_processors):
        if num_processors <= 0 or not isinstance(num_processors, int):
            raise IOError('Number of processors should be a positive integer')
        else:
            self.master.reconfigure(num_processors=num_processors)
            self._num_processors = num_processors

    @cache_theta.setter
    def cache_theta(self, cache_theta):
        if not isinstance(cache_theta, bool):
            raise IOError('cache_theta should be bool')
        else:
            self.master.reconfigure(cache_theta=cache_theta)
            self._cache_theta = cache_theta

    @theta_columns_naming.setter
    def theta_columns_naming(self, theta_columns_naming):
        if theta_columns_naming not in ['id', 'title']:
            raise IOError('theta_columns_naming should be either id or title')
        else:
            self._theta_columns_naming = theta_columns_naming

    @num_topics.setter
    def num_topics(self, num_topics):
        if num_topics <= 0 or not isinstance(num_topics, int):
            raise IOError('Number of topics should be a positive integer')
        else:
            self._num_topics = num_topics

    @topic_names.setter
    def topic_names(self, topic_names):
        if not topic_names:
            raise IOError('Number of topic names should be non-negative')
        else:
            self._topic_names = topic_names
            self._num_topics = len(topic_names)

    @class_ids.setter
    def class_ids(self, class_ids):
        if len(class_ids) < 0:
            raise IOError('Number of (class_id, class_weight) pairs should be non-negative')
        else:
            self._class_ids = class_ids

    # ========== METHODS ==========
    def load_dictionary(self, dictionary_name=None, dictionary_path=None):
        """ARTM.load_dictionary() --- load the BigARTM dictionary of
        the collection into the lib

        Args:
          dictionary_name (str): the name of the dictionary in the lib, default=None
          dictionary_path (str): full file name of the dictionary, default=None
        """
        if dictionary_path is not None and dictionary_name is not None:
            self.master.import_dictionary(filename=dictionary_path,
                                          dictionary_name=dictionary_name)
        elif dictionary_path is None:
            raise IOError('dictionary_path is None')
        else:
            raise IOError('dictionary_name is None')

    def save_dictionary(self, dictionary_name=None, dictionary_path=None):
        """ARTM.save_dictionary() --- save the BigARTM dictionary of
        the collection on the disk

        Args:
          dictionary_name (str): the name of the dictionary in the lib, default=None
          dictionary_path (str): full file name for the dictionary, default=None
        """
        if dictionary_path is not None and dictionary_name is not None:
            self.master.export_dictionary(filename=dictionary_path,
                                          dictionary_name=dictionary_name)
        elif dictionary_path is None:
            raise IOError('dictionary_path is None')
        else:
            raise IOError('dictionary_name is None')

    def save_text_dictionary(self, dictionary_name=None, dictionary_path=None, encoding='utf-8'):
        """ARTM.save_text_dictionary() --- save the BigARTM dictionary of
        the collection on the disk in the human readable text format

        Args:
          dictionary_name (str): the name of the dictionary in the lib, default=None
          dictionary_path (str): full file name for the text dictionary file, default=None
          encoding (str): an encoding of text in diciotnary
        """
        if dictionary_path is not None and dictionary_name is not None:
            dictionary_data = self.master.get_dictionary(dictionary_name)
            with codecs.open(dictionary_path, 'w', encoding) as fout:
                fout.write(u'name: {}\n'.format(dictionary_data.name))
                fout.write(u'token, class_id, token_value, token_tf, token_df\n')

                for i in xrange(len(dictionary_data.token)):
                    fout.write(u'{0}, {1}, {2}, {3}, {4}\n'.format(dictionary_data.token[i],
                                                                   dictionary_data.class_id[i],
                                                                   dictionary_data.token_value[i],
                                                                   dictionary_data.token_tf[i],
                                                                   dictionary_data.token_df[i]))

        elif dictionary_path is None:
            raise IOError('dictionary_path is None')
        else:
            raise IOError('dictionary_name is None')

    def load_text_dictionary(self, dictionary_name=None, dictionary_path=None, encoding='utf-8'):
        """ARTM.load_text_dictionary() --- load the BigARTM dictionary of
        the collection from the disk in the human readable text format

        Args:
          dictionary_name (str): the name for the dictionary in the lib, default=None
          dictionary_path (str): full file name of the text dictionary file, default=None
          encoding (str): an encoding of text in diciotnary
        """
        if dictionary_path is not None and dictionary_name is not None:
            dictionary_data = messages.DictionaryData()
            with codecs.open(dictionary_path, 'r', encoding) as fin:
                dictionary_data.name = fin.next().split(' ')[1][0: -1]
                fin.next()  # skip comment line

                for line in fin:
                    line_list = line.split(' ')
                    dictionary_data.token.append(line_list[0][0: -1])
                    dictionary_data.class_id.append(line_list[1][0: -1])
                    dictionary_data.token_value.append(float(line_list[2][0: -1]))
                    dictionary_data.token_tf.append(float(line_list[3][0: -1]))
                    dictionary_data.token_df.append(float(line_list[4][0: -1]))

            self.master.create_dictionary(dictionary_data=dictionary_data,
                                          dictionary_name=dictionary_name)

        elif dictionary_path is None:
            raise IOError('dictionary_path is None')
        else:
            raise IOError('dictionary_name is None')

    def create_dictionary(self, dictionary_name=None, dictionary_data=None):
        """ARTM.save_dictionary() --- save the BigARTM dictionary of
        the collection on the disk

        Args:
          dictionary_name (str): the name of the dictionary in the lib, default=None
          dictionary_data (DictionaryData instance): configuration of dictionary, default=None
        """
        if dictionary_data is not None and dictionary_name is not None:
            self.master.create_dictionary(dictionary_data=dictionary_data,
                                          dictionary_name=dictionary_name)
        elif dictionary_data is None:
            raise IOError('dictionary_data is None')
        else:
            raise IOError('dictionary_name is None')

    def gather_dictionary(self, dictionary_target_name=None, data_path=None, cooc_file_path=None,
                          vocab_file_path=None, symmetric_cooc_values=False):
        """ARTM.gather_dictionary() --- create the BigARTM dictionary of
        the collection, represented as batches and load it in the lib

        Args:
          dictionary_target_name (str): the name of the dictionary in the lib, default=None
          data_path (str): full path to batches folder
          cooc_file_path (str): full path to the file with cooc info
          vocab_file_path (str): full path to the file with vocabulary.
          If given, the dictionary token will have the same order, as in this file,
          otherwise the order will be random, default=None
          symmetric_cooc_values (str): if the cooc matrix should
          considered to be symmetric or not, default=False
        """
        if dictionary_target_name is not None and data_path is not None:
            self.master.gather_dictionary(dictionary_target_name=dictionary_target_name,
                                          data_path=data_path,
                                          cooc_file_path=cooc_file_path,
                                          vocab_file_path=vocab_file_path,
                                          symmetric_cooc_values=symmetric_cooc_values)
        elif data_path is None:
            raise IOError('data_path is None')
        else:
            raise IOError('dictionary_target_name is None')

    def filter_dictionary(self, dictionary_name=None, dictionary_target_name=None, class_id=None,
                          min_df=None, max_df=None,
                          min_df_rate=None, max_df_rate=None,
                          min_tf=None, max_tf=None,):
        """ARTM.filter_dictionary() --- filter the BigARTM dictionary of
        the collection, which was already loaded into the lib

        Args:
           dictionary_name (str): name of the dictionary in the lib to filter
           dictionary_target_name (str): name for the new filtered dictionary in the lib
           class_id (str): class_id to filter
           min_df (float): min df value to pass the filter
           max_df (float): max df value to pass the filter
           min_df_rate (float): min df rate to pass the filter
           max_df_rate (float): max df rate to pass the filter
           min_tf (float): min tf value to pass the filter
           max_tf (float): max tf value to pass the filter
        """
        if dictionary_name is not None:
            self.master.filter_dictionary(dictionary_target_name=dictionary_target_name,
                                          dictionary_name=dictionary_name,
                                          class_id=class_id,
                                          min_df=min_df,
                                          max_df=max_df,
                                          min_df_rate=min_df_rate,
                                          max_df_rate=max_df_rate,
                                          min_tf=min_tf,
                                          max_tf=max_tf)
        else:
            raise IOError('dictionary_name is None')

    def remove_dictionary(self, dictionary_name=None):
        """ARTM.remove_dictionary() --- remove the loaded BigARTM dictionary
        from the lib

        Args:
          dictionary_name (str): the name of the dictionary in th lib, default=None
        """
        if dictionary_name is not None:
            self._lib.ArtmDisposeDictionary(self.master.master_id, dictionary_name)
        else:
            raise IOError('dictionary_name is None')

    def fit_offline(self, batch_vectorizer=None, num_collection_passes=20,
                    num_document_passes=1, reuse_theta=True, dictionary_filename=DICTIONARY_NAME):
        """ARTM.fit_offline() --- proceed the learning of
        topic model in off-line mode

        Args:
          batch_vectorizer: an instance of BatchVectorizer class
          num_collection_passes (int): number of iterations over whole given
          collection, default=20
          num_document_passes (int): number of inner iterations over each document
          for inferring theta, default=1
          reuse_theta (bool): using theta from previous pass of the collection,
          defaul=True

          dictionary_filename (str): the name of file with dictionary to use in inline
          initialization, default='dictionary'

        Note:
          ARTM.initialize() should be proceed before first call
          ARTM.fit_offline(), or it will be initialized by dictionary
          during first call.
        """
        if batch_vectorizer is None:
            raise IOError('No batches were given for processing')

        if not self._initialized:
            dictionary_name = '{0}:{1}'.format(dictionary_filename, str(uuid.uuid4()))
            self.master.import_dictionary(
                dictionary_name=dictionary_name,
                filename=os.path.join(batch_vectorizer.data_path, dictionary_filename))

            self.initialize(dictionary_name=dictionary_name)
            self.remove_dictionary(dictionary_name)

        # temp code for easy using of TopicSelectionThetaRegularizer from Python
        topic_selection_regularizer_name = []

        theta_reg_name, theta_reg_tau, phi_reg_name, phi_reg_tau = [], [], [], []
        for name, config in self._regularizers.data.iteritems():
            if str(config.__class__.__bases__[0].__name__) == 'BaseRegularizerTheta':
                theta_reg_name.append(name)
                theta_reg_tau.append(config.tau)

                # temp code for easy using of TopicSelectionThetaRegularizer from Python
                _topic_selection_regularizer_func_1(self,
                                                    topic_selection_regularizer_name,
                                                    config,
                                                    name)
            else:
                phi_reg_name.append(name)
                phi_reg_tau.append(config.tau)

        class_ids, class_weights = [], []
        for class_id, class_weight in self._class_ids.iteritems():
            class_ids.append(class_id)
            class_weights.append(class_weight)

        batches_list = [batch.filename for batch in batch_vectorizer.batches_list]
        for _ in xrange(num_collection_passes):
            # temp code for easy using of TopicSelectionThetaRegularizer from Python
            _topic_selection_regularizer_func_2(self, topic_selection_regularizer_name)

            self.master.process_batches(pwt=self.model_pwt,
                                        batches=batches_list,
                                        nwt=self.model_nwt,
                                        regularizer_name=theta_reg_name,
                                        regularizer_tau=theta_reg_tau,
                                        num_inner_iterations=num_document_passes,
                                        class_ids=class_ids,
                                        class_weights=class_weights,
                                        reset_scores=True,
                                        reuse_theta=reuse_theta)
            self._synchronizations_processed += 1
            self.master.regularize_model(pwt=self.model_pwt,
                                         nwt=self.model_nwt,
                                         rwt=self.model_rwt,
                                         regularizer_name=phi_reg_name,
                                         regularizer_tau=phi_reg_tau)
            self.master.normalize_model(nwt=self.model_nwt, pwt=self.model_pwt, rwt=self.model_rwt)

            for name in self.scores.data.keys():
                if name not in self.score_tracker:
                    self.score_tracker[name] =\
                        SCORE_TRACKER[self.scores[name].type](self.scores[name])

                    for _ in xrange(self._synchronizations_processed - 1):
                        self.score_tracker[name].add()

                self.score_tracker[name].add(self.scores[name])

    def fit_online(self, batch_vectorizer=None, tau0=1024.0, kappa=0.7,
                   update_every=1, num_document_passes=10, reset_theta_scores=False,
                   dictionary_filename=DICTIONARY_NAME):
        """ARTM.fit_online() --- proceed the learning of topic model
        in on-line mode

        Args:
          batch_vectorizer: an instance of BatchVectorizer class
          update_every (int): the number of batches; model will be updated once per it,
          default=1
          tau0 (float): coefficient (see kappa), default=1024.0
          kappa (float): power for tau0, default=0.7

          The formulas for decay_weight and apply_weight:
          update_count = current_processed_docs / (batch_size * update_every)
          rho = pow(tau0 + update_count, -kappa)
          decay_weight = 1-rho
          apply_weight = rho

          num_document_passes (int): number of inner iterations over each document
          for inferring theta, default=10
          reset_theta_scores (bool): reset accumulated Theta scores
          before learning, default=False

          dictionary_filename (str): the name of file with dictionary to use in inline
          initialization, default='dictionary'

        Note:
          ARTM.initialize() should be proceed before first call
          ARTM.fit_online(), or it will be initialized by dictionary
          during first call.
        """
        if batch_vectorizer is None:
            raise IOError('No batches were given for processing')

        if not self._initialized:
            dictionary_name = '{0}:{1}'.format(dictionary_filename, str(uuid.uuid4()))
            self.master.import_dictionary(
                dictionary_name=dictionary_name,
                filename=os.path.join(batch_vectorizer.data_path, dictionary_filename))

            self.initialize(dictionary_name=dictionary_name)
            self.remove_dictionary(dictionary_name)

        # temp code for easy using of TopicSelectionThetaRegularizer from Python
        topic_selection_regularizer_name = []

        theta_reg_name, theta_reg_tau, phi_reg_name, phi_reg_tau = [], [], [], []
        for name, config in self._regularizers.data.iteritems():
            if str(config.__class__.__bases__[0].__name__) == 'BaseRegularizerTheta':
                theta_reg_name.append(name)
                theta_reg_tau.append(config.tau)

                # temp code for easy using of TopicSelectionThetaRegularizer from Python
                _topic_selection_regularizer_func_1(self,
                                                    topic_selection_regularizer_name,
                                                    config,
                                                    name)
            else:
                phi_reg_name.append(name)
                phi_reg_tau.append(config.tau)

        class_ids, class_weights = [], []
        for class_id, class_weight in self._class_ids.iteritems():
            class_ids.append(class_id)
            class_weights.append(class_weight)

        batches_list = [batch.filename for batch in batch_vectorizer.batches_list]
        batches_to_process = []
        cur_processed_docs = 0
        for batch_idx, batch_filename in enumerate(batches_list):
            batches_to_process.append(batch_filename)
            if ((batch_idx + 1) % update_every == 0) or ((batch_idx + 1) == len(batches_list)):
                # temp code for easy using of TopicSelectionThetaRegularizer from Python
                _topic_selection_regularizer_func_2(self, topic_selection_regularizer_name)

                self.master.process_batches(pwt=self.model_pwt,
                                            batches=batches_to_process,
                                            nwt='nwt_hat',
                                            regularizer_name=theta_reg_name,
                                            regularizer_tau=theta_reg_tau,
                                            num_inner_iterations=num_document_passes,
                                            class_ids=class_ids,
                                            class_weights=class_weights,
                                            reset_scores=reset_theta_scores)

                cur_processed_docs += batch_vectorizer.batch_size * update_every
                update_count = cur_processed_docs / (batch_vectorizer.batch_size * update_every)
                rho = pow(tau0 + update_count, -kappa)
                decay_weight, apply_weight = 1 - rho, rho

                self._synchronizations_processed += 1
                if self._synchronizations_processed == 1:
                    self.master.merge_model(
                        models={self.model_pwt: decay_weight, 'nwt_hat': apply_weight},
                        nwt=self.model_nwt,
                        topic_names=self._topic_names)
                else:
                    self.master.merge_model(
                        models={self.model_nwt: decay_weight, 'nwt_hat': apply_weight},
                        nwt=self.model_nwt,
                        topic_names=self._topic_names)

                self.master.regularize_model(pwt=self.model_pwt,
                                             nwt=self.model_nwt,
                                             rwt=self.model_rwt,
                                             regularizer_name=phi_reg_name,
                                             regularizer_tau=phi_reg_tau)

                self.master.normalize_model(nwt=self.model_nwt,
                                            pwt=self.model_pwt,
                                            rwt=self.model_rwt)
                batches_to_process = []

                for name in self.scores.data.keys():
                    if name not in self.score_tracker:
                        self.score_tracker[name] =\
                            SCORE_TRACKER[self.scores[name].type](self.scores[name])

                        for _ in xrange(self._synchronizations_processed - 1):
                            self.score_tracker[name].add()

                    self.score_tracker[name].add(self.scores[name])

    def save(self, filename='artm_model'):
        """ARTM.save() --- save the topic model to disk

        Args:
          filename (str): the name of file to store model, default='artm_model'
        """
        if not self._initialized:
            raise RuntimeError('Model does not exist yet. Use ARTM.initialize()/ARTM.fit_*()')

        if os.path.isfile(filename):
            os.remove(filename)
        self.master.export_model(self.model_pwt, filename)

    def load(self, filename):
        """ARTM.load() --- load the topic model,
        saved by ARTM.save(), from disk

        Args:
          filename (str) --- the name of file containing model, no default

        Note:
          Loaded model will overwrite ARTM.topic_names and
          ARTM.num_topics fields. Also it will empty
          ARTM.score_tracker.
        """
        self.master.import_model(self.model_pwt, filename)
        self._initialized = True
        topic_model = self.master.get_phi_info(model=self.model_pwt)
        self._topic_names = [topic_name for topic_name in topic_model.topic_name]
        self._num_topics = topic_model.topics_count

        # Remove all info about previous iterations
        self._score_tracker = {}
        self._synchronizations_processed = 0

    def get_phi(self, topic_names=None, class_ids=None, model_name=None):
        """ARTM.get_phi() --- get custom Phi matrix of model. The
                              extraction of the whole Phi matrix expects
                              ARTM.phi_ call.

        Args:
          topic_names (list of str): list with topics to extract,
          default=None (means all topics)
          class_ids (list of str): list with class ids to extract,
          default=None (means all class ids)
          model_name (str): self.model_pwt by default,
          self.model_nwt is also reasonable to extract unnormalized counters

        Returns:
          pandas.DataFrame: (data, columns, rows), where:
          1) columns --- the names of topics in topic model
          2) rows --- the tokens of topic model
          3) data --- content of Phi matrix
        """
        if not self._initialized:
            raise RuntimeError('Model does not exist yet. Use ARTM.initialize()/ARTM.fit_*()')

        valid_model_name = self.model_pwt if model_name is None else model_name
        phi_info = self.master.get_phi_info(model=valid_model_name)
        nd_array = self.master.get_phi_matrix(model=valid_model_name,
                                              topic_names=topic_names,
                                              class_ids=class_ids)

        tokens = [token for token, class_id in zip(phi_info.token, phi_info.class_id)
                  if class_ids is None or class_id in class_ids]
        topic_names = [topic_name for topic_name in phi_info.topic_name
                       if topic_names is None or topic_name in topic_names]
        phi_data_frame = DataFrame(data=nd_array,
                                   columns=topic_names,
                                   index=tokens)

        return phi_data_frame

    def get_theta(self, topic_names=None, remove_theta=False):
        """ARTM.get_theta() --- get Theta matrix for training set
        of documents

        Args:
          topic_names (list of str): list with topics to extract,
          default=None (means all topics)
          remove_theta (bool): flag indicates save or remove Theta from model
          after extraction, default=False

        Returns:
          pandas.DataFrame: (data, columns, rows), where:
          1) columns --- the ids of documents, for which the Theta
          matrix was requested
          2) rows --- the names of topics in topic model, that was
          used to create Theta
          3) data --- content of Theta matrix
        """
        if self.cache_theta is False:
            raise ValueError('cache_theta == False. Set ARTM.cache_theta = True')
        if not self._initialized:
            raise RuntimeError('Model does not exist yet. Use ARTM.initialize()/ARTM.fit_*()')

        theta_info = self.master.get_theta_info(model=self.model_pwt)

        column_names = []
        if self._theta_columns_naming == 'title':
            column_names = [item_title for item_title in theta_info.item_title]
        else:
            column_names = [item_id for item_id in theta_info.item_id]

        all_topic_names = [topic_name for topic_name in theta_info.topic_name]
        use_topic_names = topic_names if topic_names is not None else all_topic_names
        nd_array = self.master.get_theta_matrix(model=self.model_pwt,
                                                topic_names=use_topic_names,
                                                clean_cache=remove_theta)

        theta_data_frame = DataFrame(data=nd_array.transpose(),
                                     columns=column_names,
                                     index=use_topic_names)
        return theta_data_frame

    def fit_transform(self, topic_names=None, remove_theta=False):
        """ARTM.fit_transform() --- obsolete way of theta retrieval.
        Use get_theta instead.
        """
        return self.get_theta(topic_names, remove_theta)

    def transform(self, batch_vectorizer=None, num_document_passes=1, predict_class_id=None):
        """ARTM.transform() --- find Theta matrix for new documents

        Args:
          batch_vectorizer: an instance of BatchVectorizer class
          num_document_passes (int): number of inner iterations over each document
          for inferring theta, default = 1
          predict_class_id (string): class_id of a target modality to predict, default = None.
          When this option is enabled the resulting columns of theta matrix will correspond
          to unique labels of a target modality. The values will represent p(c|d), which give
          the probability of class label c for document d.

        Returns:
          pandas.DataFrame: (data, columns, rows), where:
          1) columns --- the ids of documents, for which the Theta
          matrix was requested
          2) rows --- the names of topics in topic model, that was
          used to create Theta
          3) data --- content of Theta matrix.
        """
        if batch_vectorizer is None:
            raise IOError('No batches were given for processing')

        if not self._initialized:
            raise RuntimeError('Model does not exist yet. Use ARTM.initialize()/ARTM.fit_*()')

        class_ids, class_weights = [], []
        for class_id, class_weight in self._class_ids.iteritems():
            class_ids.append(class_id)
            class_weights.append(class_weight)

        batches_list = [batch.filename for batch in batch_vectorizer.batches_list]
        theta_info, nd_array = self.master.process_batches(pwt=self.model_pwt,
                                                           batches=batches_list,
                                                           nwt='nwt_hat',
                                                           num_inner_iterations=num_document_passes,
                                                           class_ids=class_ids,
                                                           class_weights=class_weights,
                                                           find_theta=True,
                                                           predict_class_id=predict_class_id)

        document_ids = [item_id for item_id in theta_info.item_id]
        topic_names = [topic_name for topic_name in theta_info.topic_name]
        theta_data_frame = DataFrame(data=nd_array.transpose(),
                                     columns=document_ids,
                                     index=topic_names)
        return theta_data_frame

    def initialize(self, dictionary_name=None, seed=-1):
        """ARTM.initialize() --- initialize topic model before learning

        Args:
          dictionary_name (str): the name of loaded BigARTM collection
          dictionary, default=None
          seed (unsigned int or -1): seed for random initialization, default=-1 (no seed)

        """
        self._lib.ArtmDisposeModel(self.master.master_id, self.model_pwt)
        self._lib.ArtmDisposeModel(self.master.master_id, self.model_nwt)
        self._lib.ArtmDisposeModel(self.master.master_id, self.model_rwt)
        self.master.initialize_model(model_name=self.model_pwt,
                                     dictionary_name=dictionary_name,
                                     num_topics=self._num_topics,
                                     topic_names=self._topic_names,
                                     seed=seed)

        phi_info = self.master.get_phi_info(model=self.model_pwt)
        self._topic_names = [topic_name for topic_name in phi_info.topic_name]
        self._initialized = True

        # Remove all info about previous iterations
        self._score_tracker = {}
        self._synchronizations_processed = 0
