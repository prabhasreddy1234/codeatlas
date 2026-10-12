from app.analyzer.java_extractor import parse_java
from app.analyzer.kotlin_extractor import parse_kotlin

KT = b"""package com.x

import a.b.C
import a.b.*
import a.b.D as Alias

interface Foo {
    fun bar()
}

object Registry

enum class Color { RED, GREEN }

annotation class Marker

open class Base

class Impl(private val c: C) : Base(), Foo {
    constructor() : this(C())

    override fun bar() {
        c.run(1)
        helper()
    }

    companion object {
        fun make() = Impl()
    }
}

fun topLevel() {}
"""

JAVA = b"""package com.y;

import a.b.C;
import static a.b.D.helper;

public interface Shape extends Comparable<Shape> { double area(); }

enum Mode { A, B }

public abstract class Base implements Shape {
    protected C field;
    public Base(int x) {}
    public void go() { field.run(); helper(); new C(); }
}
"""


def kinds(pf):
    return {t.name: t.kind for t in pf.types}


def test_kotlin_declarations():
    pf = parse_kotlin("A.kt", KT)
    assert pf.package == "com.x" and not pf.has_errors
    assert kinds(pf) == {"Foo": "interface", "Registry": "object", "Color": "enum",
                         "Marker": "annotation", "Base": "class", "Impl": "class"}
    impl = next(t for t in pf.types if t.name == "Impl")
    assert [m.name for m in impl.methods if m.kind == "function"] == ["bar"]
    assert sum(1 for m in impl.methods if m.kind == "constructor") == 2
    assert impl.nested[0].is_companion and impl.nested[0].methods[0].name == "make"
    assert [f.name for f in pf.functions] == ["topLevel"]
    foo = next(t for t in pf.types if t.name == "Foo")
    assert foo.methods[0].name == "bar" and foo.methods[0].start == 8


def test_kotlin_imports_and_supertypes():
    pf = parse_kotlin("A.kt", KT)
    assert [(i.path, i.wildcard, i.alias) for i in pf.imports] == [
        ("a.b.C", False, None), ("a.b", True, None), ("a.b.D", False, "Alias")]
    impl = next(t for t in pf.types if t.name == "Impl")
    assert [(s.name, s.ctor_call) for s in impl.supers] == [("Base", True), ("Foo", False)]


def test_kotlin_calls():
    pf = parse_kotlin("A.kt", KT)
    bar = next(m for t in pf.types if t.name == "Impl" for m in t.methods if m.name == "bar")
    assert [(c.receiver, c.name, c.argc) for c in bar.calls] == [("c", "run", 1), (None, "helper", 0)]


def test_java_declarations_and_inheritance():
    pf = parse_java("A.java", JAVA)
    assert pf.package == "com.y"
    assert kinds(pf) == {"Shape": "interface", "Mode": "enum", "Base": "class"}
    assert [(i.path, i.static) for i in pf.imports] == [("a.b.C", False), ("a.b.D.helper", True)]
    base = next(t for t in pf.types if t.name == "Base")
    assert [(s.name, s.ctor_call) for s in base.supers] == [("Shape", False)]
    shape = next(t for t in pf.types if t.name == "Shape")
    assert [s.name for s in shape.supers] == ["Comparable"]
    assert [m.kind for m in base.methods] == ["constructor", "function"]
    calls = {(c.receiver, c.name, c.kind) for c in base.methods[1].calls}
    assert calls == {("field", "run", "call"), (None, "helper", "call"), (None, "C", "new")}
