# -*- coding: utf-8 -*-

""" Useful functions for the pke module. """

import csv
import glob
import gzip
import codecs
import logging
from collections import defaultdict

from .base import LoadFile
from .supervised import Kea

from nltk.stem.snowball import SnowballStemmer as Stemmer


def load_document_frequency_file(input_file,
                                 delimiter='\t'):
    """ Load a csv file containing document frequencies. Automatically detects
        if input file is compressed (gzip) if extension is '.gz'.

        Args:
            input_file (str): the input file containing document frequencies in
                csv format.
            delimiter (str): the delimiter used for separating term-document
                frequencies tuples, defauts to '\t'.

        Returns:
            frequencies (dic): a dictionary of the form {term_1: freq,
                term_2: freq}, freq being an integer.
    """

    # initialize the DF dictionary
    frequencies = {}

    # open the input file
    with gzip.open(input_file, 'r') if input_file.endswith('.gz') else \
         codecs.open(input_file, 'r') as f:

        # read the csv file
        df_reader = csv.reader(f, delimiter=delimiter)

        # populate the dictionary
        for row in df_reader:
            frequencies[row[0]] = int(row[1])

    # return the populated dictionary
    return frequencies


def compute_document_frequency(input_dir,
                               output_file,
                               format="corenlp",
                               extension="xml",
                               use_lemmas=False,
                               stemmer="porter",
                               stoplist=None,
                               delimiter='\t',
                               n=3):
    """ Compute n-gram document frequencies from a set of input documents. An
        extra row is added to the output file for specifying the number of
        documents from which the frequencies were computed (--NB_DOC-- tab XX).

        Args:
            input_dir (str): the input directory.
            output_file (str): the output file.
            format (str): the input files format, defaults to corenlp.
            extension (str): file extension for input documents, defaults to
                xml.
            use_lemmas (bool): whether lemmas from stanford corenlp are used
                instead of stems (computed by nltk), defaults to False.
            stemmer (str): the stemmer in nltk to used (if used), defaults
                to porter.
            stoplist (list): the stop words for filtering n-grams, default to
                None.
            delimiter (str): the delimiter between n-grams and document
                frequencies, default to tabulation.
            n (int): the length for ngrams, defaults to 3.
    """

    # document frequency container
    frequencies = defaultdict(set)

    # initialize number of documents
    nb_documents = 0

    # loop throught the documents
    for input_file in glob.glob(input_dir+'/*.'+extension):

        # initialize load file object
        doc = LoadFile(input_file)

        # read the input file
        doc.read_document(format=format,
                          use_lemmas=use_lemmas,
                          stemmer=stemmer,
                          sep='/')

        # loop through sentences
        for sentence in doc.sentences:

            skip = min(n, sentence.length)
            lowercase_words = [u.lower() for u in sentence.words]

            for j in range(sentence.length):
                for k in range(j+1, min(j+1+skip, sentence.length+1)):

                    if set(lowercase_words[j:k]).intersection(stoplist):
                        continue

                    ngram = ' '.join(sentence.stems[j:k]).lower()
                    frequencies[ngram].add(input_file)

        nb_documents += 1

    # Dump the df container
    with gzip.open(output_file, 'w') as f:

        # add the number of documents as special token
        f.write('--NB_DOC--'+delimiter+str(nb_documents)+'\n')

        for ngram in frequencies:
            f.write((ngram).encode('utf-8') + delimiter +
                    str(len(frequencies[ngram])) + '\n')



def train_supervised_model(input_dir,
                           reference_file,
                           model_file,
                           df=None,
                           format="corenlp",
                           use_lemmas=False,
                           stemmer="porter",
                           model=Kea(),
                           language='english',
                           extension="xml",
                           sep_doc_id=':',
                           sep_ref_keyphrases=',',
                           reference_stemming=False):
    """ Build a supervised keyphrase extraction model from a set of documents
        and a reference file.

        Args:
            input_dir (str): the input directory.
            reference_file (str): the reference file.
            model_file (str): the model output file.
            df (dict): df weights dictionary.
            format (str): the input files format, defaults to corenlp.
            use_lemmas (bool): weither lemmas from stanford corenlp are used
                instead of stems (computed by nltk), defaults to False.
            stemmer (str): the stemmer in nltk to used (if used), defaults
                to porter.
            model (pke.supervised object): the supervised model to train,
                defaults to a Kea object.
            extension (str): file extension for input documents, defaults to
                xml.
            sep_doc_id (str): the separator used for doc_id in reference file,
                defaults to ':'.
            sep_ref_keyphrases (str): the separator used for keyphrases in
                reference file, defaults to ','.
    """

    logging.info('building model '+str(model)+' from '+input_dir)

    references = load_references(reference_file,
                                 sep_doc_id=sep_doc_id,
                                 sep_ref_keyphrases=sep_ref_keyphrases,
                                 reference_stemming=reference_stemming,
                                 stemmer=stemmer)
    training_instances = []
    training_classes = []
    files = glob.glob(input_dir+'/*.'+extension)

    # get the input files from the input directory
    for input_file in files:

        logging.info('reading file '+input_file)

        # initialize the input file
        model.__init__(input_file=input_file, language=language)

        doc_id = input_file.split('/')[-1].split('.')[0]

        model.read_document(format=format,
                            use_lemmas=use_lemmas,
                            stemmer=stemmer,
                            sep='/')

        # select candidates using default method
        model.candidate_selection()

        # extract features
        model.feature_extraction(df=df, training=True)

        # annotate the reference keyphrases in the instances
        for candidate in model.instances:
            if candidate in references[doc_id]:
                training_classes.append(1)
            else:
                training_classes.append(0)
            training_instances.append(model.instances[candidate])

    logging.info('writing model to '+model_file)
    model.train(training_instances=training_instances,
                training_classes=training_classes,
                model_file=model_file)


def load_references(input_file,
                    sep_doc_id=':',
                    sep_ref_keyphrases=',',
                    reference_stemming=False,
                    stemmer='porter'):
    """ Load a reference file and returns a dictionary. """

    logging.info('loading reference keyphrases from '+input_file)

    references = defaultdict(list)

    with codecs.open(input_file, 'r', 'utf-8') as f:
        for line in f:
            cols = line.strip().split(sep_doc_id)
            doc_id = cols[0].strip()
            keyphrases = cols[1].strip().split(sep_ref_keyphrases)
            for v in keyphrases:
                if '+' in v:
                    for s in v.split('+'):
                        references[doc_id].append(s)
                else:
                    references[doc_id].append(v)
            if reference_stemming:
                for i, k in enumerate(references[doc_id]):
                    stems = [Stemmer(stemmer).stem(u) for u in k.split()]
                    references[doc_id][i] = ' '.join(stems)

    return references
