
__doc__ = """
This module contains code to parse the constant pool in a Java .class file
for use in dependency analysis.
"""
__author__ = "Mark C. Chu-Carroll"

import io
import re

class ClassFileParseError(Exception):
  """Exception raised when a class file cannot be parsed"""
  def __init__(self, file, msg):
    """
    Parameters:
      file: the path to the .class file containing the error
      msg: a message describing the specific error.
    """
    self.file = file
    self.msg = msg

def bytesToInt(bytes, len):
  """
  Utility function which takes a leading  sequence of bytes in big-endian format from a string,
  and converts them into an integer.

  Parameters:
    bytes: a string or array containing the bytes
    len: the length of the sequence to convert.
  Returns: an integer value.
  """
  result = 0
  for b in range(len):
    result = (result << 8) + ord(bytes[b])
  return result

def readInt(inp, len):
  """
  Utility function which reads a group of bytes from a binary input stream
  and converts them to an integer.

  Parameters:
    inp a binary input stream
    len the number of bytes to read.
  Returns: an integer value.
  """
  bytes = inp.read(len)
  return bytesToInt(bytes, len)

# A regular expression matcher for recognizing class references
# in Java type signature strings. The class file format for a class
# reference is a capital L, followed by the class name in path format,
# terminated by semicolon.
#
# Type signatures appear in two places:
# - in a method reference, describing the type signature of the method.
# - in a class reference to an array type (e.g., "]Ljava/lang/Object;" for
#    an array of object.)
#
# Parametric types cause some trouble here. A parametric can appear
# as LTypeA<LTypeB;>;.
#
# We cheat a bit here, and say that L introduces a type, and it's
# ended by either <, >, or ;.
#
# So if we saw a string (like this actual one)
# "Lscala/Option<Lcom/foursquare/auth/AuthorizableUser;>;"
# our regex would match "Lscala/Option<", and "Lcom/foursquare/auth/AuthorizableUser;"
# as referenced class names.
ClassPatternRE = re.compile("L([A-Za-z_0-9/$]*)[<>;]")

class CPEntry(object):
  """
  An abstract representation for a Java class file constant pool entry.
  """

  CP_ENTRY_TYPES = ['none', 'STRING', 'none', 'INT', 'FLOAT', 'LONG', 'DOUBLE',
        'CLASSREF', 'STRINGREF', 'FIELDREF', 'METHODREF', 'IMETHODREF',
        'NAMEANDTYPE' ]

  def getClassNamesFromString(self, str):
    """
    Given a type descriptor string, extract any named class reference.
    eg, given "java/lang/String", just return "java/lang/String",
    but for "]]Ljava/lang/String;", return "java/lang/String".
    """
    if str.startswith("["):
      matches = ClassPatternRE.findall(str)
      if matches is None:
        return []
      else:
        return matches
    else:
      return [ str ]

  def getEntryType(self):
    """
    Returns: an integer value specifying the constant pool entry type of this entry,
      using the numeric identifiers specified by the Java class file specification.
    """
    pass

  def getEntryTypeName(self):
    """ Returns: the constant pool entry type in human-readable form."""
    return CPEntry.CP_ENTRY_TYPES[self.getEntryType()]

  def getReferencedClasses(self, pool):
    """ Returns a list of all classes that are referenced by this constant pool entry. """
    return []

class CPStringEntry(CPEntry):
  """
  A string entry in the constant pool.
  This is represented in the class file as a 2-byte length, followed by
  a sequence of length bytes containing the string value in UTF8 format.
  """

  def __init__(self, strValue):
    """
    Parameters:
      strValue: the string value for this pool entry.
    """
    self.strval = strValue

  def getEntryType(self):
    return 1

  def getString(self):
    """ Returns the string value in this pool entry."""
    return self.strval

  def __str__(self):
    return "String(%s)" % self.getString()

class CPEmpty(CPEntry):
  """
  Empty slot in the constant pool.
  When a pool entry is long or double, it takes 2 CP slots, so the
  second slot is empty.
  """
  def __str__(self):
    return "EMPTY"

  def getEntryType(self):
    return 0


class CPIgnoredEntry(CPEntry):
  """
  A constant pool entry whose contents we don't care about.

  We only care about the classpath fields that could resolve to classes.
  Other fields we don't parse in detail; we just record their type identifier
  and their data in binary form.
  """
  def __init__(self, entryType, data):
    """
    Parameters:
      entryType: the constant pool entry type
      data: the data for this entry in binary form.
    """
    self.entryType = entryType
    self.data = data

  def __str__(self):
    return "Ignored(type: %s)" % self.getEntryTypeName()

  def getEntryType(self):
    return self.entryType

class CPClassRef(CPEntry):
  """
  A constant pool entry describing a class reference.
  A class reference is a field containing the integer index of a string entry
  in the constant pool containing the name of the class.
  """

  def __init__(self, idx):
    """
    Parameters:
      idx the index of the string entry in the pool containing the name of the referenced class.
    """
    self.idx = idx

  def __str__(self):
    return "ClassRef(%s)" % self.idx

  def getReferencedClasses(self, pool):
    return  self.getClassNamesFromString(self.getClassName(pool))

  def getEntryType(self):
    return 7

  def getClassName(self, pool):
    """ Returns the name of the class referenced by this entry. """
    return pool.entryAt(self.idx).getString()


class CPFieldRef(CPEntry):
  """
  A constant pool entry describing a reference to an object field.
  A field reference constant pool entry consists of two indices.
  The first is the CP index of a class reference entry;
  The second is the CP index of a string entry containing the name of the field.
  """

  def __init__(self, clazzIdx, fieldIdx):
    """
    Parameters:
      clazzIdx the index of the pool entry containing a reference to the class
      fieldIdx the index of the pool entry containing the string name of this field.
    """
    self.clazzIdx = clazzIdx
    self.fieldIdx = fieldIdx

  def getReferencedClasses(self, pool):
    return self.getClassNamesFromString(self.getClassName(pool))

  def getClassName(self, pool):
    """ Returns the name of the class referenced by this entry. """
    return pool.entryAt(self.clazzIdx).getClassName(pool)

  def getEntryType(self):
    return 9

  def __str__(self):
    return "Field(%s, %s)" % (self.clazzIdx, self.fieldIdx)




class CPMethodRef(CPEntry):
  """
  A constant pool entry representing a method reference.
  A method reference is a pair of indices:
  the first is the CP index of the class reference;
  the second is the CP index of a method descriptor.

  The constant pool actually defines two different entry types for class method references,
  and interface method references, which are identical.
  """

  def __init__(self, entryType, classIdx, methIdx):
    """
    Parameters:
      entryType: the CP entry type - either 10 (for class method) or 11 (for interface method)
      classIdx: the index of the class reference entry for this method.
    """
    self.entryType = entryType
    self.classIdx = classIdx
    self.methIdx = methIdx

  def getClassName(self, pool):
    """ Returns the name of the class whose method is specified by this entry. """
    return self.getClassNamesFromString(pool.entryAt(self.classIdx).getClassName(pool))

  def getEntryType(self):
    return self.entryType

  def getReferencedClasses(self, pool):
    return pool.entryAt(self.methIdx).getReferencedClasses(pool)

  def __str__(self):
    typename = ''
    if self.getEntryType() == 10:
      typename = "Method"
    elif self.getEntryType() == 11:
      typename = "IMethod"
    else:
      typename = "ERROR"
    return "%s(%s, %s)" % (typename, self.classIdx, self.methIdx)

class CPMethodDescriptor(CPEntry):
  """
  A constant pool entry representing a method descriptor.

  A method descriptor is represented by a pair of CP indices:
  the first is the index of a string containing the method name;
  the second is the index of a string containing the method signature
  """

  def __init__(self, nameIdx, sigIdx):
    """
    Parameters:
      nameIdx: the constant pool index of the entry containing the method name.
      sigIdx: the constant pool index of a string entry containing the method parameter spec.
    """
    self.nameIdx = nameIdx
    self.sigIdx = sigIdx


  def getName(self, pool):
    return pool.entryAt(self.nameIdx).getString()

  def getSignature(self, pool):
    return pool.entryAt(self.sigIdx).getString()

  def getParamClassNames(self, pool):
    descriptor = self.getSignature(pool)
    matches = CPMethodDescriptor.ClassPatternRE.findall(descriptor)
    if matches is None:
      return []
    else:
      return matches

  def getReferencedClass(self, pool):
    return self.getParamClassNames(pool)

  def getEntryType(self):
    return 12

  def __str__(self):
    return "Descript(%s, %s)" % (self.nameIdx, self.sigIdx)


class JavaConstantPool(object):
  """
  A class representing a Java .class file constant pool.

  Example usage:
    e = "~/classes/foo/bar/baz.class"
    poolE = JavaConstantPool(e)
    poolE.parse()
    print "E references classes: %s" % cle.getReferencedClasses()
  """

  def __init__(self, classfile):
    """
    Parameters:
      classfile: the pathname of a java .class file.
    """
    self.file = classfile

  def parse(self):
    """
    Read the class file and populate this constant pool with its contents.

    Raises ClassfileParseError if the file isn't a valid .class file.
    """
    inp = io.FileIO(self.file, mode="r")
    magic = readInt(inp, 4)
    if magic != 0xCAFEBABE:
      raise ClassFileParseError(self.file, "Invalid class file: magic# incorrect")
    discard_major = readInt(inp, 2)
    discard_minor = readInt(inp, 2)

    num_entries = readInt(inp, 2)
    entries = []
    i = 0
    while i < num_entries:
      new_entry = self.read_cp_entry(inp)
      entries.append(new_entry)
      if new_entry.getEntryType() == 5 or new_entry.getEntryType() == 6:
        entries.append(CPEmpty())
        i = i + 2
      else:
        i = i + 1
    inp.close()
    self.entries = entries

  def entryAt(self, i):
    """
    Returns the constant pool entry with a specified index.
    Note: Java class files use 1-based indices for the constant pool.
    """
    return self.entries[i - 1]

  def dump(self):
    """
    Debug method for printing the constant pool in readable format.
    """
    print "[CONSTANT POOL for class file '%s']" % self.file
    for num in range(len(self.entries)):
      print "\t%s => %s" % (num + 1, self.entries[num])

  def read_cp_entry(self, inp):
    """
    Read and parse a single constant pool entry.
    Parameters:
      inp: an open binary stream pointing at a constant pool entry.
    """
    i = ord(inp.read(1))

    if i == 0:
      return CPIgnoredEntry(0, "")
    if i == 1: # String entry
      strlen = readInt(inp, 2)
      str = inp.read(strlen)
      return CPStringEntry(str)
    elif i == 3: # int entry, 4 bytes
      bytes = inp.read(4)
      return CPIgnoredEntry(3, bytes)
    elif i == 4: # float entry, 4 bytes
      bytes = inp.read(4)
      return CPIgnoredEntry(4, bytes)
    elif i == 5: #  long
      bytes = inp.read(8)
      return CPIgnoredEntry(5, bytes)
    elif i == 6: # double
      bytes = inp.read(8)
      return CPIgnoredEntry(6, bytes)
    elif i == 7: #class ref
      idx = readInt(inp, 2)
      return CPClassRef(idx)
    elif i == 8: # string ref
      idx = readInt(inp, 2)
      return CPStringEntry(idx)
    elif i == 9: # field ref
      clidx = readInt(inp, 2)
      fidx = readInt(inp, 2)
      return CPFieldRef(clidx, fidx)
    elif i == 10: # method reference
      clidx = readInt(inp, 2)
      midx = readInt(inp, 2)
      return CPMethodRef(10, clidx, midx)
    elif i == 11: # interface method reference
      clidx = readInt(inp, 2)
      midx = readInt(inp, 2)
      return CPMethodRef(11, clidx, midx)
    elif i == 12: # method name descriptor
      midx = readInt(inp, 2)
      sidx = readInt(inp, 2)
      return CPMethodDescriptor(midx, sidx)
    else:
      raise ClassFileParseError(self.file, "Invalid constant pool entry")

  def getReferencedClasses(self):
    result = set([])
    for e  in self.entries:
       result = result.union(e.getReferencedClasses(self))
    return result


#e = "../foursquare.web/.pants.d/scalac/incremental.classes/core.src.main.scala.com.foursquare.hairball/com/foursquare/pages/ConcretePageActions$$anonfun$_createPage$2.class"
#cle = JavaConstantPool(e)
#cle.parse()
#print "E references %s" % cle.getReferencedClasses()

