import os
import conllu
import joblib
from sklearn.preprocessing import LabelEncoder
from torch import tensor
from torch.utils.data import Dataset, IterableDataset

import edit_scripts

# Overriding the parser for the conllu reader. This is needed so that feats can be read in as a str instead of a dict
OVERRIDDEN_FIELD_PARSERS = {
    "id": lambda line, i: conllu.parser.parse_id_value(line[i]),
    "xpos": lambda line, i: conllu.parser.parse_nullable_value(line[i]),
    "feats": lambda line, i: conllu.parser.parse_nullable_value(
        line[i]
    ),
    "head": lambda line, i: conllu.parser.parse_int_value(line[i]),
    "deps": lambda line, i: conllu.parser.parse_paired_list_value(line[i]),
    "misc": lambda line, i: conllu.parser.parse_dict_value(line[i]),
}


# TODO https://universaldependencies.org/u/feat/index.html if I need the full enumerable possibilities of ufeats.


class ConlluMapDataset(Dataset):
    """Conllu Map Dataset, used for small training/validation sets

    This class loads the entire dataset into memory and is therefore only suitable for smaller datasets
    """
    PAD_TAG = "[PAD]"
    UPOS_CLASSES = [
        "ADJ",
        "ADP",
        "ADV",
        "AUX",
        "CCONJ",
        "DET",
        "INTJ",
        "NOUN",
        "NUM",
        "PART",
        "PRON",
        "PROPN",
        "PUNCT",
        "SCONJ",
        "SYM",
        "VERB",
        "X",
        "_",
    ]

    def __init__(self, conllu_file: str, reverse_edits: bool = False, path_name: str = "UDTube"):
        """Initializes the instance based on user input.

        Args:
            conllu_file: The path to the conllu file to make the dataset from
            reverse_edits: Reverse edit script calculation. Recommended for suffixal languages. False by default
        """
        super().__init__()
        self.path_name = path_name
        self.conllu_file = conllu_file
        self.e_script = (
            edit_scripts.ReverseEditScript
            if reverse_edits
            else edit_scripts.EditScript
        )
        # setting up label encoders
        if conllu_file:
            # TODO confirm that the encoders are the same for train and val
            self.upos_encoder = LabelEncoder()
            self.ufeats_encoder = LabelEncoder()
            self.lemma_encoder = LabelEncoder()
            self.feats_classes = self._get_all_classes("feats")
            self.lemma_classes = self._get_all_classes("lemma")
            self._fit_label_encoders()
            self.data_set = self._get_data()
        else:
            # Instatiation of empty class, happens in prediction
            self.data_set = []

    def _fit_label_encoders(self):
        # this ensures that the PAD ends up last
        self.upos_encoder.fit(self.UPOS_CLASSES + [self.PAD_TAG])
        self.ufeats_encoder.fit(self.feats_classes + [self.PAD_TAG])
        self.lemma_encoder.fit(self.lemma_classes + [self.PAD_TAG])
        # saving all the encoders
        if not os.path.exists(self.path_name):
            os.mkdir(self.path_name)
        joblib.dump(self.upos_encoder, f'{self.path_name}/upos_encoder.joblib')
        joblib.dump(self.ufeats_encoder, f'{self.path_name}/ufeats_encoder.joblib')
        joblib.dump(self.lemma_encoder, f'{self.path_name}/lemma_encoder.joblib')

    def _get_all_classes(self, lname: str):
        """helper function to get all the classes observed in the training set"""
        classes = []
        with open(self.conllu_file) as f:
            dt = conllu.parse_incr(f, field_parsers=OVERRIDDEN_FIELD_PARSERS)
            for tk_list in dt:
                for tok in tk_list:
                    if lname != "lemma" and tok[lname] not in classes:
                        classes.append(tok[lname])
                    elif lname == "lemma":
                        lrule = str(
                            self.e_script(
                                tok["form"].lower(), tok[lname].lower()
                            )
                        )
                        if lrule not in classes:
                            classes.append(lrule)
        return classes

    def _get_data(self):
        """Loads in the conllu data and prepares it as a list dataset so that it can be indexed for __getitem__"""
        data = []
        with open(self.conllu_file) as f:
            dt = conllu.parse_incr(f, field_parsers=OVERRIDDEN_FIELD_PARSERS)
            for tk_list in dt:
                sentence = tk_list.metadata["text"]
                uposes = []
                lemma_rules = []
                ufeats = []
                for tok in tk_list:
                    l_rule = str(
                        self.e_script(
                            tok["form"].lower(), tok["lemma"].lower()
                        )
                    )
                    uposes.append(tok["upos"])
                    lemma_rules.append(l_rule)
                    ufeats.append(tok["feats"])
                uposes = self.upos_encoder.transform(uposes)
                lemma_rules = self.lemma_encoder.transform(lemma_rules)
                ufeats = self.ufeats_encoder.transform(ufeats)
                data.append((sentence, uposes, lemma_rules, ufeats))
        return data

    def __len__(self):
        return len(self.data_set)

    def __getitem__(self, idx):
        return self.data_set[idx]


class ConlluIterDataset(IterableDataset):
    """
    :param IterableDataset:
    :return:
    """

    def __init__(self, conllu_file: str, reverse_edits: bool = False, path_name: str = "UDTube"):
        super().__init__()
        if conllu_file:
            self.conllu_file = open(conllu_file)
        if os.path.exists(path_name):
            self.upos_encoder = joblib.load(f'{path_name}/upos_encoder.joblib')
            self.ufeats_encoder = joblib.load(f'{path_name}/ufeats_encoder.joblib')
            self.lemma_encoder = joblib.load(f'{path_name}/lemma_encoder.joblib')
        self.e_script = (
            edit_scripts.ReverseEditScript
            if reverse_edits
            else edit_scripts.EditScript
        )

    def __iter__(self):
        dt = conllu.parse_incr(self.conllu_file, field_parsers=OVERRIDDEN_FIELD_PARSERS)

        def _generator():
            for tk_list in dt:
                sentence = tk_list.metadata["text"]
                uposes = []
                lemma_rules = []
                ufeats = []
                for tok in tk_list:
                    l_rule = str(
                        self.e_script(
                            tok["form"].lower(), tok["lemma"].lower()
                        )
                    )
                    uposes.append(tok["upos"])
                    lemma_rules.append(l_rule)
                    ufeats.append(tok["feats"])
                uposes = self.upos_encoder.transform(uposes)
                lemma_rules = self.lemma_encoder.transform(lemma_rules)
                ufeats = self.ufeats_encoder.transform(ufeats)
                yield sentence, uposes, lemma_rules, ufeats

        return _generator()

    def __del__(self):
        if hasattr(self, "conllu_file"):
            self.conllu_file.close()  # want to make sure we close the file during garbage collection


class TextIterDataset(IterableDataset):
    """Iterable dataset, used for inference when labels are unknown

    This class is used when the data for inference is large and we do not want to load it entirely into memory.
    """
    def __init__(self, text_file: str):
        """Initializes the instance based on user input.

        Args:
            text_file: The path to the textfile to incrementally read from.
        """
        super().__init__()
        if text_file:
            self.tf = open(text_file)

    def __iter__(self):
        return self.tf

    def __del__(self):
        if hasattr(self, "tf"):
            self.tf.close()  # want to make sure we close the file during garbage collection
