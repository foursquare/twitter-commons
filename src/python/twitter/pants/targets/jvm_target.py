# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

from twitter.pants.base.payload import JvmTargetPayload
from twitter.pants.base.target import Target

from .exclude import Exclude
from .jarable import Jarable


class JvmTarget(Target, Jarable):
  """A base class for all java module targets that provides path and dependency translation."""

  def __init__(self,
               address=None,
               sources=None,
               provides=None,
               excludes=None,
               configurations=None,
               *args, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`twitter.pants.base.address.Address`.
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param excludes: One or more :class:`twitter.pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param configurations: One or more ivy configurations to resolve for this target.
      This parameter is not intended for general use.
    :type configurations: tuple of strings
    """

    payload = JvmTargetPayload(sources=sources,
                               sources_rel_path=address.spec_path,
                               provides=provides,
                               excludes=excludes,
                               configurations=configurations)
    super(JvmTarget, self).__init__(*args, address=address, payload=payload, **kwargs)

    self.add_labels('jvm')
