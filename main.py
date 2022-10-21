"""Named Entity Linking annotation tool

This is a bare-bones command line tool that allows for much quicker annotation
than a general annotation tool like Brat provides.

Requirements:
$ pip install requests==2.28.1

Starting the tool:
$ python main.py [--debug] [--demo]

With debugging the tool works the same but will print messages to the
standard output. In demo mode a small file is added for demo purposes.

Assumptions:
- all annotations are extents
- no annotations with fragments

This tools presents named entities one by one, the annotator has no say on the
order that the entities are presented in.

Any URL can be handed in as a link, but the assumption is that links are made
to Wikipedia at https://en.wikipedia.org/wiki/Main_Page, for example to
https://en.wikipedia.org/wiki/Jim_Lehrer. If a link is to the English Wikipedia
then instead of the full link we can just enter "Jim_Lehrer" or "Jim Lehrer"
and it will be automatically expanded to the full Wikipedia URL.

Location of source files and NER annotations:
- source files: https://github.com/clamsproject/wgbh-collaboration
- annotations: https://github.com/clamsproject/clams-aapb-annotations

These repositories should be cloned locally. Set the variables SOURCES and
ENTITIES below to reflect the paths into the local clones.

"""

# TODO: should not assume that all annotations are extents
# TODO: change the confusing way the code deals with the different extensions


import sys
import collections

import requests

import config
from utils import ANSI
from model import Corpus, LinkAnnotation, LinkAnnotations

# Locations of the source and entity annotation repositories, edit as needed
SOURCES = '../../wgbh-collaboration/21'
ENTITIES = '../../clams-aapb-annotations/uploads/2022-jun-namedentity/annotations'

# No edits should be needed below this line


class Warnings(object):
    NO_ENTITY = 'no entity was selected, type "n" to select next entity'
    UNKNOWN_COMMAND = 'unknown command, type "h" to see available commands'
    NO_LINK_SUGGESTION = 'there was no link suggestion'
    NOT_IN_WIKIPEDIA = "'%s' is not an entry in Wikipedia"


class Annotator(object):

    """The annotation tool itself. Controls all user interactions and delegates
    the work of adding annotations to the embedded LinkAnnotations instance.

    corpus: Corpus                -  the corpus that the annotator runs on
    next_entity: EntityType       -  the next entity to be annotated
    action: str                   -  user provided action
    link_suggestion: str          -  a link suggestion generated by the tool
    annotations: LinkAnnotations  -  all annotations generated so far

    """

    def __init__(self, corpus: Corpus, annotations_file: str):
        self.corpus = corpus
        self.action = None
        self.next_entity = None
        self.link_suggestion = None
        self.annotations = LinkAnnotations(corpus, annotations_file)

    def loop(self):
        self.action = None
        self.link_suggestion = None
        while True:
            self.debug_loop('START OF LOOP:')
            if self.action in ('q', 'quit', 'exit'):
                break
            elif self.action is None:
                self.status()
            elif self.action in ('?', 'h', 'help'):
                self.print_help()
            elif self.action in ('s', 'status'):
                self.status()
            elif self.action in ('b', 'backup'):
                self.action_backup()
            elif self.action in ('', 'n'):
                self.action_print_next()
            elif self.action == 'a':
                self.action_print_annotations()
            elif self.action == 'y':
                self.action_accept_hint()
            elif self.action.startswith('f '):
                self.action_fix_link(self.action[2:])
            elif self.action.startswith('a '):
                self.action_print_annotations(self.action[2:])
            elif self.action.startswith('c '):
                self.action_set_context(self.action[2:])
            elif self.action == 'l' or self.action.startswith('l '):
                link = '-' if self.action == 'l' else self.action[2:].strip()
                self.action_store_link(link)
            else:
                self.print_warning(Warnings.UNKNOWN_COMMAND)
            self.debug_loop('END OF LOOP, BEFORE PROMPT:')
            self.action = input("\n%s " % config.PROMPT).strip()

    def action_backup(self):
        self.annotations.backup()

    def action_accept_hint(self):
        if self.next_entity is None:
            self.print_warning(Warnings.NO_ENTITY)
        elif self.link_suggestion is None:
            self.print_warning(Warnings.NO_LINK_SUGGESTION)
            self.action_print_next()
        else:
            self.next_entity.link = self.link_suggestion
            self.annotations.add_link(self.next_entity, self.link_suggestion)
            self.action_print_next()

    def action_store_link(self, link: str):
        link = LinkAnnotations.normalize_link(link)
        if self.next_entity is not None:
            if self.validate_link(link):
                self.next_entity.link = link
                self.annotations.add_link(self.next_entity, link)
            else:
                self.print_warning(Warnings.NOT_IN_WIKIPEDIA % link)
            self.action_print_next()
            if config.DEBUG:
                for a in self.annotations[-5:]:
                    print(a)
        else:
            self.print_warning(Warnings.NO_ENTITY)

    def action_fix_link(self, identifier_and_link: str):
        identifier, link = identifier_and_link.split(' ', 1)
        identifier = int(identifier)
        link = LinkAnnotations.normalize_link(link)
        if self.validate_link(link):
            old_annotation = self.annotations.get_annotation(identifier)
            new_annotation = self.annotations.create_link(link, annotation=old_annotation)
            new_annotation = LinkAnnotation('\t'.join([str(f) for f in new_annotation]))
            self.annotations.save_annotation(new_annotation)
        else:
            self.print_warning(Warnings.NOT_IN_WIKIPEDIA % link)

    def action_print_next(self):
        self.next_entity = self.corpus.next()
        text = self.next_entity.text()
        entity_class = self.next_entity.entity_class()
        print("\n%s[%s] (%s)%s\n" % (ANSI.BOLD, text, entity_class, ANSI.END))
        for entity in self.next_entity:
            corpus_file = self.corpus.files.get(entity.file_name)
            left, right = corpus_file.get_context(entity)
            left = (config.CONTEXT_SIZE-len(left)) * ' ' + left
            print('    %s[%s%s%s]%s' % (left, ANSI.BLUE, text, ANSI.END, right))
        self.link_suggestion = self.suggest_link(text)
        if self.link_suggestion:
            print('\nLink suggestion: %s' % self.link_suggestion)

    def action_print_annotations(self, search_term=None):
        if search_term is None:
            print("\nCurrent annotations:\n")
            for annotation in self.annotations:
                print(annotation.as_pretty_line())
        else:
            print("\nAnnotations matching '%s':\n" % search_term)
            for annotation in self.annotations:
                if search_term.lower() in annotation.text.lower():
                    print(annotation.as_pretty_line())

    @staticmethod
    def action_set_context(context_size: str):
        try:
            n = int(context_size)
            config.CONTEXT_SIZE = n
        except ValueError:
            print('\nWARNING: context size has to be an integer, ignoring command')

    @staticmethod
    def validate_link(link: str):
        """A link entered by the user is okay if it is either an empty link or
        it exists as a URL."""
        if not link:
            return True
        return True if requests.get(link).status_code == 200 else False

    def suggest_link(self, entity_text: str):
        suggestions = []
        for corpus_file in self.corpus.get_files():
            suggestion = corpus_file.data.get(entity_text)
            if suggestion is not None and suggestion.link is not None:
                suggestions.append(suggestion.link)
        c = collections.Counter(suggestions)
        try:
            return c.most_common()[0][0]
        except IndexError:
            return None

    def status(self):
        print("\nStatus on %s\n" % self.corpus.annotations_folder)
        corpus_types = 0
        corpus_types_done = 0
        for corpus_file in self.corpus.get_files():
            (total_types, types_done, percent_done_types) = corpus_file.status()
            corpus_types += total_types
            corpus_types_done += types_done
            print('    %s  %4d %3d%%' % (corpus_file.name,
                                         corpus_file.entity_type_count(),
                                         round(percent_done_types)))
        corpus_percentage_done = round((corpus_types_done/corpus_types) * 100)
        print('    %-39s  %4d %3d%%' % ('', corpus_types, corpus_percentage_done))

    def debug_loop(self, message: str):
        if config.DEBUG:
            print("\n%s" % message)
            print("    self.action           =  %s" % self.action)
            print("    self.link_suggestion  =  %s" % self.link_suggestion)
            print("    self.next_entity      =  %s" % self.next_entity)

    @staticmethod
    def print_help():
        with open('help.txt') as fh:
            print("\n%s" % fh.read().strip())

    @staticmethod
    def print_warning(message: str):
        print('\n%sWARNING: %s%s' % (ANSI.RED, message, ANSI.END))


if __name__ == '__main__':

    args = sys.argv[1:]
    if '--debug' in args:
        config.DEBUG = True
    if '--demo' in args:
        config.DEMO = True
    Annotator(Corpus(ENTITIES, SOURCES), config.ANNOTATIONS).loop()
