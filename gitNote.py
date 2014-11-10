#!/usr/bin/env python
import argparse
import codecs
from datetime import datetime
import subprocess
import textwrap
import markdown2
import os
import re
from slugify import slugify

try:
    import ujson as json
except ImportError:
    import json

try:
    ROOT = os.environ["GITNOTE_ROOT"]
except KeyError:
    raise SystemExit("Environment variable for blog root not set")

class Git:
    """
    Context manager to add relevant folders
    to git and commit on exit, returns an iterator
    object of changed markdown files in notes/ sub-
    directory.
    """

    def __init__(self, message="GitNote Commit"):
        self.FNULL = open(os.devnull,'w')
        self.message = message


    def __enter__(self):
        for loc in ['notes/','data.json','images/']:
            subprocess.call(['git', 'add', '--ignore-removal', loc], cwd=ROOT, 
                             stdout=self.FNULL, stderr=subprocess.STDOUT)
        return self

    def _changed_files(self):
        with Cd(ROOT):
            changed_files = subprocess.check_output(['git','diff',
                            '--name-only','HEAD']).split('\n')[:-1]
            relevant_changes = [f for f in changed_files if f[-3:]=='.md'
                                and os.path.isfile(ROOT+f)]
        return relevant_changes

    def __iter__(self):
        for item in self._changed_files():
                yield item

    def __exit__(self,exc_type, exc_value, traceback):
        if exc_type is not None:
            print exc_type, exc_value, traceback
        subprocess.Popen(['git', '--no-pager', 'commit', '-m', self.message],cwd=ROOT)
        self.FNULL.close()


class CLIParse:
    """
    Parse command line arguments
    """

    @staticmethod
    def _sanity_check():
        """
        Performs basic sanity checks
        before running.
        """
        assert os.path.isdir(ROOT), "Path does not exist!"
        assert os.path.exists(ROOT+'.git'), "Git repository hasn't been initialized"
        with Cd(ROOT):
            assert subprocess.check_output([
                    'git','remote', '-v','show']), """Remote not detected, refer 
                    README to set offline flag."""

    def __init__(self):


        CLIParse._sanity_check()
        parser = argparse.ArgumentParser(
            description="CLI Note Manager v1",
            usage="gitnote <command> [<args>,]"
            )
        parser.add_argument('command', help="One of inline, new, or build")
        parser.add_argument('-b', '--body', help="Body of your note")
        parser.add_argument('-t', '--title', help="Title of your note")
        parser.add_argument('-g', '--tags', help="Tags for your note")
        self.args = parser.parse_args()
        if not hasattr(self,self.args.command):
            print "Unrecognized command"
            parser.print_help()
            exit(1)
        getattr(self, self.args.command)()

    def _parse_tags(self):
        return self.args.tags if self.args.tags is not None else None

    def _get_date(self):
        return datetime.now().strftime("%d-%m-%Y %H:%M:%S")

    def _save_note(self,contents,title):
        note_dir = os.path.join(ROOT,'notes')
        filename = os.path.join(note_dir,slugify(title)+'.md')
        if os.path.exists(filename):
            choice = raw_input("Exists. Enter no to exit, yes to overwrite.")
            if choice == 'yes':
                with open(filename,'w') as f:
                    f.write(contents)
        return filename

    def _get_args(self):
        return self.args.title,self.args.body,self._parse_tags(),self._get_date()

    def inline(self):
        if self.args.title is None or self.args.body is None:
            raise SystemExit("Title and body required, try --help")
        title, body, tags, date = self._get_args()
        nt = Note(title,body,tags,date)
        print "Saved at: ", self._save_note(str(nt),title)

    def new(self):
        if self.args.title is None:
            raise SystemExit("Title and body required, try --help")
        title, _, tags, date = self._get_args()
        text = "#{0}\n\nCreated on {2}\nTags:{1}".format(title,tags,date)
        fname = self._save_note(text,title)
        os.system('{0} {1}'.format('xdg-open', fname))

    def build(self):
        with Git() as g:
            for cf in g:
                title,body,date,tags = parse_md(filename)
                nt = Note(title,body,tags,date)
                ndb = NoteDB()
                ndb.post(nt)

class Note:
    """
    Blueprint for a note
    """

    def __init__(self,title,content=None,tags=[],nid=None,
                 date=datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                 ):
        self.title = title
        self.content_raw = content if content is not None else ''
        self.content = '' if content is None else self.md_to_html(content)
        self.id = nid
        self.tags = tags
        self.date_created = date

    def md_to_html(self, text):
        """
        markdown to html conversion
        """
        if self.content_raw:
            return markdown2.markdown(text, extras=['fenced-code-blocks'])
        else:
            raise SystemExit("Body required for programmatic conversion")

    def _check_type(func):
            def wrapped(self, *args):
                for arg in args:
                    assert isinstance(arg, Note), "comparables must belong to the same class"
                func(self, *args)
            return wrapped

    @_check_type
    def __eq__(self, note):
        return self.title == note.title and self.content == note.content

    @_check_type
    def __ge__(self, note):
        return self.date_created >= note.date_created

    def __str__(self):
        return textwrap.dedent("""\
        #{0}
        {1}
        Posted on {2}
        Tags: {3}
        """.format(self.title,self.content_raw,self.date_created,
                   ",".join(self.tags or [])).encode('utf-8'))

    __repr__ = __str__


class NoteDB:
    """
    CRUD operations on JSON file
    api-methods:
    
    all_entries(): returns all note entries
    get_entry(id): returns entry by id
    search_entry(query): returns entries having a match for query
    post_entry(note): posts a Note object to DB
    """

    def __init__(self):
        """
        data: holds dictionary of all posts. For structure refer Note class.
        """
        self.data = self._get_db()

    def _get_db(self):
        if os.path.isfile(ROOT+"data.json"):
            with codecs.open(ROOT+"data.json",encoding='utf-8') as json_file:
                data = json.load(json_file)
            return data
        else:
            """File doesn't exist, create it."""
            author = raw_input("Enter your name: ")
            blog_title = raw_input("Blog title: ")
            content = {
                "Blog Title": blog_title,
                "Author": author,
                "count": 0,
                "notes": [],
                "pages": []
            }
            self._write_data(content)
            return content

    def _write_data(self,data):
        data['count'] = len(data['notes'])
        with codecs.open(ROOT+"data.json",encoding='utf-8',mode='w') as f:
            json.dump(data,f,ensure_ascii=False)

    def _new_id(self, note):
        if not note.id:
            maxid=max([n['id'] for n in self.data['notes'] if n['id'] is not None])
            return maxid+1
        return note.id

    def _note_to_dict(self,note,nid=None):
        _id = self._new_id(note) if nid is None else nid
        return {
            "id": _id,
            "title": note.title,
            "content": note.content,
            "tags": note.tags,
            "date_created": note.date_created
        }

    def all_entries(self):
        for note in self.data['notes']:
            print "{0} -- {1}".format(note['id'],note['title'])

    def post(self, note):
        assert isinstance(note, Note), "Can't post: not a Note object"
        titles = [n['title'] for n in self.data['notes']]
        if note.title not in titles:
            self.data['notes'].append(self._note_to_dict(note))
            self._write_data(self.data)
        else:
            for i,n in enumerate(self.data['notes']):
                if note.title == n['title']:
                    self.data['notes'][i] = self._note_to_dict(note,nid=n['id'])
                    self._write_data(self.data)

def parse_md(filename):
    with open(filename,'r') as f:
        s = f.read()
    title = re.findall(r'#(.+)\n',s)[0]
    tags = re.findall(r'Tags:(.+)',s)[0].strip().split(',')
    date = re.findall(r'Posted on (.+)',s)[0].strip()
    body = re.findall(r'\n([^#].*)Posted on', s, re.S)[0].strip()
    tags = tags if tags!=[''] else None
    return title,body,date,tags

class Cd:
    """
    Convenience class for changing current working directory
    and returning to original on exiting context.
    """

    def __init__(self, newPath):
        self.newPath = newPath

    def __enter__(self):
        self.savedPath = os.getcwd()
        os.chdir(self.newPath)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.savedPath)


if __name__ == '__main__':

    CLIParse()

