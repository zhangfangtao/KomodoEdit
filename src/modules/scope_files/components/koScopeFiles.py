#!python
# Copyright (c) 2014-2014 ActiveState Software Inc.
# See the file LICENSE.txt for licensing information.

# Todo: Cleanup this lib - it's becoming a mess

"""The main PyXPCOM module for Commando's Files scope"""

from xpcom.components import interfaces as Ci
from xpcom.components import classes as Cc
from xpcom import components
from xpcom.server import UnwrapObject
from findlib2 import paths_from_path_patterns
import json
import scandir
import re
import os
import logging
import threading

log = logging.getLogger("commando-scope-files-py")
#log.setLevel(10)

class koScopeFiles:

    _com_interfaces_ = [Ci.koIScopeFiles]
    _reg_desc_ = "Commando - Files Scope"
    _reg_clsid_ = "{16265b4a-4323-4250-8ef1-b4f4ee859136}"
    _reg_contractid_ = "@activestate.com/commando/koScopeFiles;1"

    _history = None
    activeUuid = None
    searches = {}

    @property
    def history(self):
        if not self._history:
            historySvc = Cc["@activestate.com/koHistoryService;1"].getService(Ci.koIHistoryService)
            self._history = UnwrapObject(historySvc)
        return self._history

    def stopExpiredSearches(self):
        for uuid in self.searches.keys():
            if uuid is not self.activeUuid:
                self.searches[uuid].stop()
                del self.searches[uuid]

    def search(self, query, uuid, path, opts, callback):
        log.debug(uuid + " - Starting Search: " + query)

        self.activeUuid = uuid
        self.stopExpiredSearches()
        
        opts = json.loads(opts)
        opts["uuid"] = uuid
        opts["callback"] = callback

        self.searches[uuid] = Searcher(opts, self.onSearchResults, self.onSearchComplete)
        t = threading.Thread(target=self.searches[uuid].start, args=(query, path))
        t.start()

    @components.ProxyToMainThreadAsync
    def onSearchResults(self, results, opts):
        if opts["uuid"] is self.activeUuid:
            log.debug(self.activeUuid + " - Passing back results")
            opts["callback"].callback(0, results)

    @components.ProxyToMainThreadAsync
    def onSearchComplete(self, opts):
        if opts["uuid"] is self.activeUuid:
            log.debug(self.activeUuid + " - Done")
            opts["callback"].callback(0, "done")

    def buildCache(self, path, opts):
        opts = json.loads(opts)
        walker = Walker(opts)
        t = threading.Thread(target=walker.start, args=(path))
        t.start()

class Searcher:

    def __init__(self, opts, callback, callbackComplete):
        self._stop = False

        self.opts = opts
        self.callback = callback
        self.callbackComplete = callbackComplete

        self.resultsPending = []
        self.resultTimer = None

        self.walker = None
        self.searchComplete = False

    def stop(self):
        self._stop = True

        if self.walker:
            self.walker.stop()

    def start(self, query, path):
        self.opts["numResults"] = 0
        self.opts["queryOriginal'"] = query
        self.opts["words"] = []

        if self.opts["queryOriginal'"] != "":
            # Prepare Regex Object
            query = ' '.join(query.split())             # Reduce/trim whitespace
            query = re.escape(query).split("\\ ")       # Escape query and split by whitespace
            self.opts["words"] = query
            query = "(" + (")(.*?)(".join(query)) + ")" # Add regex groups
            query = re.compile(query, re.IGNORECASE)
            self.opts["query"] = query

            # Prepare Replacement
            replacement = ""
            for x in range(1,query.groups+1):
                if x % 2 == 0:
                    replacement += "\\" + str(x)
                else:
                    replacement += "<html:strong>\\" + str(x) + "</html:strong>"
            self.opts["replacement"] = replacement

        # Prepate Path
        path = os.path.realpath(path)
        self.opts["path"] = path
        self.opts["stripPathRe"] = re.compile("^" + re.escape(path) + "/??")

        self.walker = Walker(self.opts, self.onWalk, self.onWalkComplete)
        self.walker.start(path)

    def onWalk(self, path, dirnames, filenames):
        for filename in dirnames + filenames:
            if self._stop:
                return

            subPath = os.path.join(path, filename)
            if subPath is self.opts["path"]:
                continue;

            replacement = subPath
            if self.opts["queryOriginal'"] != "":
                replacement = self.opts["query"].sub(self.opts["replacement"], subPath)

            if self.opts["queryOriginal'"] == "" or subPath is not replacement:
                self.opts["numResults"] = self.opts["numResults"] + 1
                if self.opts["numResults"] > self.opts.get("maxresults", 200):
                    log.debug(self.opts["uuid"] + " Max results reached")
                    return self.stop()

                if not self.opts.get("fullpath", False):
                    replacement = self.opts["stripPathRe"].sub("", replacement)

                pathEntry = {
                    "filename": filename,
                    "path": subPath,
                    "type": "dir" if filename in dirnames else "file"
                }

                self.processResult(replacement, pathEntry)

    def processResult(self, description, pathEntry):
        #log.debug(self.opts["uuid"] + " - " + pathEntry["path"])
        # Todo: figure out a good way to normalize weight numbers
        weight = 0
        depth = pathEntry["path"].count(os.sep) + 1
        weight += (10 / depth) * self.opts.get("weightDepth", 1)

        matchWeight = 0
        filename = os.path.basename(pathEntry["path"])
        for word in self.opts["words"]:
            if word in filename:
                matchWeight += 10
        weight += matchWeight * self.opts.get("weightMatch", 1)

        # cant be accessed outside of main thread
        # we should track our own usage numbers to make this more relevant
        # to the files scope specifically
        #hits = self.history.get_num_visits("file://"+pathEntry["fullPath"], -1)
        #weight += hits * opts.get("weightHits", 1)

        result = [
            pathEntry["filename"],
            pathEntry["path"],
            pathEntry["type"],
            description,
            weight
        ];

        self.returnResult(result)
        
    def returnResult(self, result):
        self.resultsPending.append(result)

        if not self.resultTimer:
            self.resultTimer = threading.Timer(0.05, self._returnResults)
            self.resultTimer.start()

    def _returnResults(self):
        self.resultTimer = None
        
        results = self.resultsPending
        self.resultsPending = []
        log.debug(self.opts["uuid"] + " - Returning " + str(len(results)) + " results")
        self.callback(results, self.opts)

        if self.searchComplete:
            self.onWalkComplete()

    def onWalkComplete(self):
        self.searchComplete = True
        
        if self._stop or self.resultsPending:
            return

        self.callbackComplete(self.opts)


class Walker:

    cache = {}

    def __init__(self, opts, callback = None, callbackComplete = None):
        self._stop = False

        self.opts = opts
        self.callback = callback
        self.callbackComplete = callbackComplete

    # Stop the active search
    def stop(self):
        self._stop = True

    # Start a new search
    def start(self, path):
        self.walk(path)

    def walk(self, path):
        dirnames = [path]
        while (len(dirnames) > 0):
            if self._stop:
                return 

            _dirnames = []
            for dirname in dirnames:
                _dirnames = _dirnames + (self.walkCache(dirname) or [])

            if self.opts.get("recursive", True):
                dirnames = _dirnames
            else:
                dirnames = []

        if self.callbackComplete:
            log.debug("Done walking directory structure")
            self.callbackComplete()

    # Walk our cache for the given path
    def walkCache(self, path):
        if not self.cache.get(path, False):
            self.cache[path] = self.scandir(path)

        # Get dirnames, filenames from cache
        [dirnames, filenames] = self.cache[path];
        
        if self.callback:
            self.callback(path, dirnames, filenames)

        return [ os.path.join(path,dirname) for dirname in dirnames ]

    def scandir(self, path):
        # Invoke the main walker lib
        walker = paths_from_path_patterns([path],
                dirs="always",
                follow_symlinks=True,
                includes=self.opts.get("includes", []),
                excludes=self.opts.get("excludes", []),
                yield_structure=True,
                recursive=False)
        for subPath, dirnames, filenames in walker: # recursive=false means we only get 1 result
            return [dirnames, filenames]
