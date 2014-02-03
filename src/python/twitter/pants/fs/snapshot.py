import os
import platform
import Queue
import shutil
import subprocess
import threading
import time
from twitter.common.dirutil import safe_mkdir_for, safe_mkdir, safe_rmtree

class Snapshotter(object):
  """A Snapshotter can provide a path to a 'snapshot' of one or more directories.
  An example use case might be snap-shotting a source tree to avoid
  seeing inconsistent sources due to change during a build.

  get() on a Snapshotter returns the path to a new snapshot
  destroy(path) expects to be handed a value previously returned by calling get() on the same

  A snapshotter delegates to a SnapshotManager dir_manager for creating and destroying directories.
  Beyond the simple mkdir/rmtree, an example dir_manager might mount and unmount ramdisks.
  """

  def __init__(self, output, root, paths, dir_manager):
    """
      `output` specifies where to create snapshots
      `root` specifies the path under which `paths` exist
      `paths` is a list of relative paths (to root) that should be snapshotted
      `dir_manager` is an instance of a SnapshotManager
    """
    self.output = os.path.realpath(os.path.abspath(output))
    self.root = os.path.realpath(os.path.abspath(root))
    if not isinstance(paths, list):
      paths = [paths]
    self.paths = paths
    if not isinstance(dir_manager, SnapshotManager):
      raise TypeError("dir manager is not a SnapshotManager?")
    self.dir_manager = dir_manager
    self.dir_manager.set_output_path(self.output)

  def _populate(self, snapshot):
    for path in self.paths:
      src = os.path.join(self.root, path)
      dest = os.path.join(snapshot, path)
      safe_mkdir_for(dest)
      shutil.copytree(src, dest)

  def get(self):
    """returns the full path to a new, ready to use, snapshot of `paths`"""
    raise NotImplementedError

  def destroy(self, snapshot):
    """destroy a snapshot previously returned by calling get() on this snapshotter"""
    self.dir_manager.destroy(snapshot)

  def start(self):
    """be ready to service calls to get() with new snapshots"""
    pass

  def stop(self):
    """no further calls to .get() will occur and all snapshots can be cleaned up"""
    self.dir_manager.cleanup()

class SnapshotManager(object):
  def cleanup(self):
    raise NotImplementedError

  def create(self):
    raise NotImplementedError

  def destroy(self, snapshot):
    raise NotImplementedError

class SimpleSnapshotManager(SnapshotManager):
  def __init__(self):
    self.num = 0

  def set_output_path(self, output_path):
    self.output = output_path

  def cleanup(self):
    for snapshot in os.listdir(self.output):
      safe_rmtree(snapshot)

  def create(self):
    snapshot = os.path.join(self.output, self.name())
    safe_mkdir(snapshot)
    return snapshot

  def destroy(self, snapshot):
    if not snapshot.startswith(self.output):
      raise ValueError('DANGER: Attempted to delete %s, which is not in: %s' % (snapshot, self.output))
    safe_rmtree(snapshot)

  def name(self):
    self.num = (self.num + 1) % 1000
    return ".snapshot-%s-%s" % (int(round(time.time() * 1000)), self.num)

class OsxRamDiskManager(SnapshotManager):
  """An OSX-specific ramdisk-based SnapshotManager, wrapping another SnapshotManager
    Useful when deleting snapshots becomes too expensive because HFS+ sucks.

    mounts path returned by other manager's create on a new ramdisk of `size` bytes and
    unmounts it during destroy before calling other manager's destroy
  """
  def __init__(self, other_manger, size):
    self.other_manger = other_manger
    self.size = size
    self.mounts = {}

  def set_output_path(self, output_path):
    self.other_manger.set_output_path(output_path)

  def create(self):
    path = self.other_manger.create()
    device = self.new_device()
    self.mount(device, path)
    return path

  def destroy(self, snapshot):
    self.unmount(snapshot)
    self.other_manger.destroy(snapshot)

  def cleanup(self):
    for path in self.mounts:
      self.unmount(path)
    self.other_manger.cleanup()

  def new_device(self):
    sectors = self.size / 512
    return _check_output(['hdid', '-nomount', 'ram://%d' % sectors]).strip()

  def mount(self, device, mount_point):
    _check_output(['newfs_hfs', '-v', 'Pants Source Snapshot', device]).strip()
    _check_output(['mount', '-t', 'hfs', device, mount_point]).strip()
    self.mounts[mount_point] = device

  def unmount(self, path):
    device = self.mounts.get(path)
    if device != None:
      _check_output(['umount', path])
      _check_output(['hdiutil', 'detach', device])
      del self.mounts[path]

  @classmethod
  def get_size(clazz, root, paths):
    def du(path):
      return int(_check_output(['du', '-ks', path]).split()[0]) * 1024
    return sum([du(os.path.join(root, path)) for path in paths])

class OnDemandSnapshotter(Snapshotter):
  """A snapshot provider that makes copies on demand, when get() is called"""
  def get(self):
    snapshot = self.dir_manager.create()
    self._populate(snapshot)
    return snapshot

class WatchingSnapshotter(Snapshotter):
  """A snapshot provider which keeps a snapshot ready by watching for changes"""
  def __init__(self, output, root, paths, dir_manager, watcher):
    super(WatchingSnapshotter, self).__init__(output, root, paths, dir_manager)
    self.watcher = watcher
    self.on_deck = Queue.Queue(1)
    self.running = threading.Event()
    self.taken = threading.Event()
    self.changed = threading.Event()
    self.producer = threading.Thread(target=self.producer_loop, name="producer")
    self.updater = threading.Thread(target=self.updater_loop, name="updater")
    self.producer.daemon = True
    self.updater.daemon = True

  def get(self):
    path = self.on_deck.get()
    self.taken.set()
    return path

  def start(self):
    self.running.set()
    self.taken.set()
    self.producer.start()
    self.updater.start()
    self.watcher.start(self.handle_change)
    super(WatchingSnapshotter, self).start()

  def producer_loop(self):
    while self.running.is_set():
      if self.taken.is_set():
        self.taken.clear()
        snapshot = self.dir_manager.create()
        self._populate(snapshot)
        try:
          self.on_deck.put(snapshot, True)
        except Queue.Full:
          self.dir_manager.destroy(snapshot)
      else:
        self.taken.wait(60)

  def updater_loop(self):
    while self.running.is_set():
      if self.changed.is_set():
        self.changed.clear()
        try:
          path = self.on_deck.get(False)
          if self.resync(path):
            try:
              self.on_deck.put(path, False)
            except Queue.Full:
              self.dir_manager.destroy(path)
          else:
            self.taken.set()
            self.dir_manager.destroy(path)
        except Queue.Empty:
          pass
      else:
        self.changed.wait(60)

  def handle_change(self, path):
    self.changed.set()

  def stop(self):
    self.running.clear()
    self.taken.set()
    self.changed.set()
    self.empty()

    super(WatchingSnapshotter, self).stop()

  def empty(self):
    while True:
      try:
        path = self.on_deck.get(False)
        self.dir_manager.destroy(path)
      except Queue.Empty:
        break

  def resync(self, snapshot):
    for path in self.paths:
      src = os.path.join(self.root, path) + os.sep # trailing slash means dest exists
      dest = os.path.join(snapshot, path) # if we didn't add trailing slash to src, we'd dirname this
      _check_output(['rsync', '-rtu', '--delete', src, dest])
    return True

class Watcher(object):
  def __init__(self, paths):
    self.paths = paths

  def start(self, callback):
    raise NotImplementedError

class FsEventsWatcher(Watcher):
  def start(self, callback):
    from fsevents import Observer, Stream
    observer = Observer()
    observer.daemon = True
    observer.start()
    stream = Stream(lambda x: callback(x.name), *self.paths, file_events=True)
    observer.schedule(stream)

#TODO(davidt): test this on a linux host
class InotifyWatcher(Watcher):
  def start(self, callback):
    import pyinotify
    class OnWriteHandler(pyinotify.ProcessEvent):
      def __init__(self, callback):
        self.callback = callback
      def process_IN_CREATE(self, event):
        self.callback(event.pathname)
      def process_IN_DELETE(self, event):
        self.callback(event.pathname)
      def process_IN_MODIFY(self, event):
        self.callback(event.pathname)
    wm = pyinotify.WatchManager()
    handler = OnWriteHandler(callback)
    notifier = pyinotify.ThreadedNotifier(wm, default_proc_fun=handler)
    for path in self.paths:
      wm.add_watch(path, pyinotify.ALL_EVENTS, rec=True, auto_add=True)
    notifier.setDaemon(True)
    notifier.start()

def get_snapshotter(output_path, root, paths,
  force_no_ramdisk=False,
  force_no_watch=False,
  size_override=None,
  ideal_ramdisk_size=1.5):
  """get a new snapshotter using file-watching if possible (unless force_no_watch is passed).
  will automatically use ramdisks on osx unless force_no_ramdisk is passed.
  if using ramdisks and size_override is not set, calls du to get size of
  paths when starting and multiplies by ideal_ramdisk_size.
  """

  manager = SimpleSnapshotManager()

  mac = platform.system() == 'Darwin'

  if mac and not force_no_ramdisk: # use ramdisks to avoid hfs+ delete perf on osx
    if size_override is not None:
      initial_size = size_override
    else:
      initial_size = int(OsxRamDiskManager.get_size(root, paths) * ideal_ramdisk_size)
    manager = OsxRamDiskManager(manager, initial_size)

  if not force_no_watch:
    roots = [os.path.join(root, path) for path in paths]
    watcher = None
    if mac:
      try:
        import fsevents
        watcher = FsEventsWatcher(roots)
      except ImportError:
        pass # TODO(davidt): warn about falling back to on-demand
    else:
      try:
        import pyinotify
        watcher = InotifyWatcher(paths)
      except ImportError:
        pass # TODO(davidt): warn about falling back to on-demand
    if watcher is not None:
      return WatchingSnapshotter(output_path, root, paths, manager, watcher)
  return OnDemandSnapshotter(output_path, root, paths, manager)

## subprocess.check_output doesn't exist in Python 2.6, so I copied this
## backport from https://gist.github.com/1027906
def _check_output(*popenargs, **kwargs):
    r"""Run command with arguments and return its output as a byte string.

    Backported from Python 2.7 as it's implemented as pure python on stdlib.

    >>> check_output(['/usr/bin/python', '--version'])
    Python 2.6.2
    """
    try:
        process = subprocess.Popen(stdout=subprocess.PIPE, *popenargs, **kwargs)
        output, unused_err = process.communicate()
        retcode = process.poll()
        if retcode:
            cmd = kwargs.get("args")
            if cmd is None:
                cmd = popenargs[0]
            error = subprocess.CalledProcessError(retcode, cmd)
            error.output = output
            raise error
        return output
    except OSError:
        return ""
