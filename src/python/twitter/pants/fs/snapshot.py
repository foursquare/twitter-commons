import multiprocessing
import os
import shutil
import subprocess
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

  def __init__(self, output, src_root, paths, dir_manager):
    """
      `output` specifies where to create snapshots
      `src_root` specifies the path under which `paths` exist
      `paths` is a list of relative paths (to src_root) that should be snapshotted
      `dir_manager` is an instance of a SnapshotManager
    """
    self.output = os.path.realpath(os.path.abspath(output))
    self.src_root = os.path.realpath(os.path.abspath(src_root))
    if not isinstance(paths, list):
      paths = [paths]
    self.paths = paths
    self.dir_manager = dir_manager

  def _populate(self, snapshot):
    for path in self.paths:
      src = os.path.join(self.src_root, path)
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
  def __init__(self, output_path):
    self.output = output_path
    self.num = 0

  def cleanup(self):
    pass

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

    mounts path returned by other manager's create on a new ramdisk of `size` megabytes and
    unmounts it during destroy before calling other manager's destroy
  """
  def __init__(self, other_manger, size):
    self.other_manger = other_manger
    self.size = size
    self.mounts = {}

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
    mb = self.size
    sectors = (1024 * 1024 * mb) / 512
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

class SimpleOnDemandSnapshotter(Snapshotter):
  """A snapshot provider that makes copies on demand, when get() is called"""
  def __init__(self, output, src_root, paths):
    super(Snapshotter, self).__init__(output, src_root, paths, SimpleSnapshotManager(output))

  def get(self):
    snapshot = self.dir_manager.create()
    self._populate(snapshot)
    return snapshot

class OnDemandRamdiskSnapshotter(SimpleOnDemandSnapshotter):
  def __init__(self, output, src_root, paths, size):
    manager = OsxRamDiskManager(SimpleSnapshotManager(output), size)
    super(SimpleOnDemandSnapshotter, self).__init__(output, src_root, paths, manager)

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
