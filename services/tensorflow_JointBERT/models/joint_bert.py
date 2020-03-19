# -*- coding: utf-8 -*-
"""
@author: mwahdan
"""

import tensorflow as tf
from tensorflow.python.keras import backend as K
from tensorflow.python.keras.models import Model
from tensorflow.python.keras.layers import Input, Dense, Multiply, TimeDistributed

from opennlu.services.tensorflow_JointBERT.models.nlu_model import NLUModel
from opennlu.services.tensorflow_JointBERT.layers.bert_layer import BertLayer
from opennlu.services.tensorflow_JointBERT.layers.albert_layer import AlbertLayer

import numpy as np
import os
import json


class JointBertModel(NLUModel):

    def __init__(self, slots_num, intents_num, bert_hub_path, sess, num_bert_fine_tune_layers=10,
                 is_bert=True, is_crf=False, learning_rate=5e-5):
        self.slots_num = slots_num
        self.intents_num = intents_num
        self.bert_hub_path = bert_hub_path
        self.num_bert_fine_tune_layers = num_bert_fine_tune_layers
        self.is_bert = is_bert
        self.is_crf = is_crf
        self.learning_rate = learning_rate
        
        self.model_params = {
                'slots_num': slots_num,
                'intents_num': intents_num,
                'bert_hub_path': bert_hub_path,
                'num_bert_fine_tune_layers': num_bert_fine_tune_layers,
                'is_bert': is_bert,
                'is_crf': False,
                'learning_rate': learning_rate
                }
        
        self.build_model()
        self.compile_model()
        
        self.initialize_vars(sess)
        
        
    def compile_model(self):
        # Instead of `using categorical_crossentropy`, 
        # we use `sparse_categorical_crossentropy`, which does expect integer targets.
        
        optimizer = tf.keras.optimizers.Adam(lr=self.learning_rate)

        losses = {
        	'slots_tagger': 'sparse_categorical_crossentropy',
        	'intent_classifier': 'sparse_categorical_crossentropy',
        }
        loss_weights = {'slots_tagger': 3.0, 'intent_classifier': 1.0}
        metrics = {'intent_classifier': 'acc'}
        self.model.compile(optimizer=optimizer, loss=losses, loss_weights=loss_weights, metrics=metrics)
        self.model.summary()
        

    def build_model(self):
        in_id = Input(shape=(None,), name='input_ids')
        in_mask = Input(shape=(None,), name='input_masks')
        in_segment = Input(shape=(None,), name='segment_ids')
        in_valid_positions = Input(shape=(None, self.slots_num), name='valid_positions')
        bert_inputs = [in_id, in_mask, in_segment, in_valid_positions]
        
        if self.is_bert:
            bert_pooled_output, bert_sequence_output = BertLayer(
                n_fine_tune_layers=self.num_bert_fine_tune_layers,
                bert_path=self.bert_hub_path,
                pooling='mean', name='BertLayer')(bert_inputs)
        else:
            bert_pooled_output, bert_sequence_output = AlbertLayer(
                fine_tune=True if self.num_bert_fine_tune_layers > 0 else False,
                albert_path=self.bert_hub_path,
                pooling='mean', name='AlbertLayer')(bert_inputs)
        
        intents_fc = Dense(self.intents_num, activation='softmax', name='intent_classifier')(bert_pooled_output)
        
        slots_output = TimeDistributed(Dense(self.slots_num, activation='softmax'))(bert_sequence_output)
        slots_output = Multiply(name='slots_tagger')([slots_output, in_valid_positions])
        
        self.model = Model(inputs=bert_inputs, outputs=[slots_output, intents_fc])

        
    def fit(self, X, Y, validation_data=None, epochs=5, batch_size=32):
        """
        X: batch of [input_ids, input_mask, segment_ids, valid_positions]
        """
        X = (X[0], X[1], X[2], self.prepare_valid_positions(X[3]))
        if validation_data is not None:
            X_val, Y_val = validation_data
            validation_data = ((X_val[0], X_val[1], X_val[2], self.prepare_valid_positions(X_val[3])), Y_val)
        
        self.model.fit(X, Y, validation_data=validation_data, 
                                 epochs=epochs, batch_size=batch_size)
 
        
        
    def prepare_valid_positions(self, in_valid_positions):
        in_valid_positions = np.expand_dims(in_valid_positions, axis=2)
        in_valid_positions = np.tile(in_valid_positions, (1, 1, self.slots_num))
        return in_valid_positions
    
        
    def initialize_vars(self, sess):
        sess.run(tf.compat.v1.local_variables_initializer())
        sess.run(tf.compat.v1.global_variables_initializer())
        K.set_session(sess)
        
        
    def predict_slots_intent(self, x, slots_vectorizer, intent_vectorizer, remove_start_end=True,
                             include_intent_prob=False):
        valid_positions = x[3]
        x = (x[0], x[1], x[2], self.prepare_valid_positions(valid_positions))
        y_slots, y_intent = self.predict(x)
        slots = slots_vectorizer.inverse_transform(y_slots, valid_positions)
        if remove_start_end:
            slots = [x[1:-1] for x in slots]
            
        if not include_intent_prob:
            intents = np.array([intent_vectorizer.inverse_transform([np.argmax(i)])[0] for i in y_intent])
        else:
            intents = np.array([(intent_vectorizer.inverse_transform([np.argmax(i)])[0], round(float(np.max(i)), 4)) for i in y_intent])
        return slots, intents
    

    def save(self, model_path):
        with open(os.path.join(model_path, 'params.json'), 'w') as json_file:
            json.dump(self.model_params, json_file, indent=2)
        self.model.save(os.path.join(model_path, 'joint_bert_model.h5'))

      
    def load(load_folder_path, sess):
        with open(os.path.join(load_folder_path, 'params.json'), 'r') as json_file:
            model_params = json.load(json_file)
            
        slots_num = model_params['slots_num'] 
        intents_num = model_params['intents_num']
        bert_hub_path = model_params['bert_hub_path']
        num_bert_fine_tune_layers = model_params['num_bert_fine_tune_layers']
        is_bert = model_params['is_bert']
        is_crf = model_params['is_crf']
        learning_rate = model_params['learning_rate']
            
        new_model = JointBertModel(slots_num, intents_num, bert_hub_path, sess, num_bert_fine_tune_layers, is_bert, is_crf, learning_rate)
        new_model.model.load_weights(os.path.join(load_folder_path,'joint_bert_model.h5'))
        
        return new_model
