from collections import defaultdict, Counter
from itertools import product
from warnings import warn

import document
from entity import Entity
from event import Event
from util import get_class_name, split_sections


class Script(object):
    def __init__(self, doc_name, entities, events):
        self.doc_name = doc_name
        if not all(isinstance(entity, Entity) for entity in entities):
            raise ParseScriptError('every entity must be a {} instance'.format(
                get_class_name(Entity)))
        self.entities = entities
        if not all(isinstance(event, Event) for event in events):
            raise ParseScriptError('every event must be a {} instance'.format(
                get_class_name(Event)))
        self.events = events

    def __eq__(self, other):
        return self.doc_name == other.doc_name \
               and all(entity == other_entity for entity, other_entity
                       in zip(self.entities, other.entities)) \
               and all(event == other_event for event, other_event
                       in zip(self.events, other.events))

    def __ne__(self, other):
        return not self.__eq__(other)

    def has_entities(self):
        return len(self.entities) > 0

    def has_events(self):
        return len(self.events) > 0

    def check_entity_idx_range(self):
        for event in self.events:
            for arg in event.get_all_args():
                if arg.entity_idx != -1 and arg.mention_idx != -1:
                    assert 0 < arg.entity_idx < len(self.entities), \
                        '{} in {} has entity_idx {} out of range'.format(
                            arg.to_text(), event.to_text(), arg.entity_idx)
                    assert 0 < arg.mention_idx < len(
                        self.entities[arg.entity_idx].mentions), \
                        '{} in {} has mention_idx {} out of range'.format(
                            arg.to_text(), event.to_text(), arg.mention_idx)

    def get_token_count(self, use_lemma=True):
        token_count = defaultdict(int)
        for event in self.events:
            for arg in event.get_all_args(include_arg_type=False):
                if arg.entity_idx == -1:
                    token_count[
                        arg.get_representation(use_lemma=use_lemma)] += 1
        for entity in self.entities:
            for mention in entity.mentions:
                for token in mention.tokens:
                    token_count[
                        token.get_representation(use_lemma=use_lemma)] += 1
        return token_count

    def get_vocab_count(self, use_lemma=True):
        vocab_count = defaultdict(Counter)
        all_args = []
        for event in self.events:
            # add the predicate of each event
            pred_representation = event.pred.get_full_representation(
                use_lemma=use_lemma)
            vocab_count['predicate'][pred_representation] += 1

            # add all prepositions of each event
            for prep, _ in event.pobj_list:
                if prep != '':
                    vocab_count['preposition'][prep] += 1
            all_args.extend(event.get_all_args(include_arg_type=False))
        for arg in all_args:
            if arg.entity_idx != -1:
                mention = self.entities[arg.entity_idx].rep_mention
                arg_representation = \
                    mention.head_token.get_representation(use_lemma=use_lemma)
                vocab_count['argument'][arg_representation] += 1
                if mention.ner != '':
                    vocab_count['name_entity'][arg_representation] += 1
                    vocab_count['name_entity_tag'][mention.ner] += 1
            else:
                arg_representation = arg.get_representation(use_lemma=use_lemma)
                vocab_count['argument'][arg_representation] += 1
                if arg.ner != '':
                    vocab_count['name_entity'][arg_representation] += 1
                    vocab_count['name_entity_tag'][arg.ner] += 1
        return vocab_count

    def to_text(self):
        entities_text = '\n'.join(['entity-{:0>3d}\t{}'.format(
            entity_idx, entity.to_text()) for entity_idx, entity
            in enumerate(self.entities)])
        events_text = '\n'.join(['event-{:0>4d}\t{}'.format(
            event_idx, event.to_text()) for event_idx, event
            in enumerate(self.events)])
        return '{}\n\nEntities:\n{}\n\nEvents:\n{}\n'.format(
            self.doc_name, entities_text, events_text)

    # entity_line_re = re.compile(r'^entity-(?P<en_idx>[\d]{3})\t(?P<en>.*)$')
    # event_line_re = re.compile(r'^event-(?P<ev_idx>[\d]{4})\t(?P<ev>.*)$')

    @classmethod
    def from_text(cls, text):
        if len(text.splitlines()) == 1:
            # Empty document: error in event extraction
            return cls(text.strip(), [], [])

        sections = split_sections(
            (l.strip() for l in text.splitlines()), ["Entities:", "Events:"])
        # First comes the doc name
        doc_name = sections[0][0].strip()
        # Then a whole section giving the entities, matched by entity_line_re
        entity_lines = [line.partition('\t')[2] for line in sections[1] if line]
        entities = [Entity.from_text(line) for line in entity_lines]
        # Then another section giving the events, matched by event_line_re
        event_lines = [line.partition('\t')[2] for line in sections[2] if line]
        events = [Event.from_text(line) for line in event_lines]

        return cls(doc_name, entities, events)

    @classmethod
    def from_doc(cls, doc):
        if not isinstance(doc, document.Document):
            raise ParseScriptError(
                'from_doc must be called with a {} instance'.format(
                    get_class_name(document.Document)))
        # get all events from document
        events = []
        # iterate through all sentences
        for sent in doc.sents:
            # iterate through all tokens
            for pred_token in sent.tokens:
                if pred_token.pos.startswith('VB'):
                    # exclude "be" verbs
                    if pred_token.lemma == 'be':
                        continue
                    # NOBUG: do not exclude stop verbs now, as both negation and
                    # particle need to be counted in detecting a stop verb,
                    # which should be excluded in constructing RichScript
                    # TODO: exclude verbs in quotes
                    # exclude modifying verbs
                    if sent.dep_graph.lookup_label(
                            'gov', pred_token.token_idx, 'xcomp'):
                        continue

                    neg = False
                    if sent.dep_graph.lookup_label('gov', pred_token.token_idx,
                                                   'neg'):
                        neg = True

                    subj_list = sent.get_subj_list(pred_token.token_idx)
                    obj_list = sent.get_obj_list(pred_token.token_idx)
                    pobj_list = sent.get_pobj_list(pred_token.token_idx)

                    if (not subj_list) and (not obj_list):
                        continue
                    if not subj_list:
                        subj_list.append(None)
                    if not obj_list:
                        obj_list.append(None)

                    for arg_tuple in product(subj_list, obj_list):
                        events.append(Event.from_tokens(
                            pred_token, neg, arg_tuple[0], arg_tuple[1],
                            pobj_list))
        if not events:
            warn('doc {} has no events'.format(doc.doc_name))
        if not doc.corefs:
            warn('doc {} has no corefs'.format(doc.doc_name))
        # get all entities from document
        entities = [Entity.from_coref(coref) for coref in doc.corefs]
        return cls(doc.doc_name, entities, events)


class ParseScriptError(Exception):
    pass


class ScriptCorpus(object):
    def __init__(self):
        self.scripts = []

    def __eq__(self, other):
        return all(script == other_script for script, other_script
                   in zip(self.scripts, other.scripts))

    def __ne__(self, other):
        return not self.__eq__(other)

    @property
    def num_scripts(self):
        return len(self.scripts)

    def add_script(self, script):
        self.scripts.append(script)

    def to_text(self):
        return '\n###DOC###\n\n'.join(script.to_text() for script in self.scripts)

    @classmethod
    def from_text(cls, text):
        script_corpus = cls()
        for script_text in text.split('\n###DOC###\n\n'):
            script_corpus.add_script(Script.from_text(script_text))
        return script_corpus
