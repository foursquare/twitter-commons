

class TargetParseProxy(object):
  '''
  This object proxies Targets during BUILD file parse time.  Its purpose is to register a set of
   Target objects constructed in the BUILD file without forcing Target to be aware of the fact
   that it's being used declaratively.
  '''

  def __init__(self, target_cls, constructed_targets):
    self._target_cls = target_cls
    self._constructed_targets = constructed_targets

  def __call__(self, *args, **kwargs):
    target = self._target_cls(*args, *kwargs)
    self._constructed_targets.add(target)
