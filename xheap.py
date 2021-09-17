#! /usr/bin/env python3

"""
xheap - heap with indexing and a few extended operation.

The primary extra feature here is that items can have
their values increased or decreased, and then have their
positions in the heap repaired.  This makes class Heap()
useful for a priority queue where the items can have
their priority increased or decreased while they are in
the queue.

Currently the caller does have to say whether the position
was increased or decreased.  We could conceivably derive
this, but most callers will probably know what they did.

Requires Python >= 3.6, due to mypy type annotations.
"""

from abc import ABC, abstractmethod
import typing


HEType = typing.TypeVar("HEType", bound="HeapEnt")


class HeapEnt(ABC):
    """
    A HeapEnt is an entry in the heap.  This provides default
    functions which maintain "pos", the position in the heap.

    A "position" of -1 means "not in the heap any more" (useful
    as an assertion for instance).

    Note that if you want to allow something to have positions
    in more than one heap, you'll need custom functions that
    use the containing heap to select the correct "pos".

    Users must provide the comparison function: define
    __lt__ to put the entry into a min-heap; define
    __gt__ to put it into a max-heap.
    """

    def __init__(self, *args, **kwargs) -> None:
        pass

    @abstractmethod
    def setpos(self, heap: "Heap", pos: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def getpos(self, heap: "Heap") -> int:
        raise NotImplementedError

    @abstractmethod
    def __lt__(self: HEType, other: HEType) -> bool:
        raise NotImplementedError

    @abstractmethod
    def __gt__(self: HEType, other: HEType) -> bool:
        raise NotImplementedError


class HVal(HeapEnt):
    """
    HVal implements a heap entry with a single simple
    comparable value "val" that will be used in a single heap.
    """

    def __init__(self, val):
        super().__init__()
        self.val = val
        self.pos = -1

    def setpos(self, heap: "Heap", pos: int) -> None:
        self.pos = pos

    def getpos(self, heap: "Heap") -> int:
        return self.pos

    def __str__(self):
        return f"HVal({self.val} @ {self.pos})"

    def __lt__(self, other: "HVal") -> bool:
        return self.val < other.val

    def __gt__(self, other: "HVal") -> bool:
        return self.val > other.val


class MultiHVal(HeapEnt):
    """
    MultiHVal implements a heap entry with a single simple
    comparable value "val" that will be used in multiple heaps.
    """

    def __init__(self, val):
        super().__init__()
        self.val = val
        self.pos = {}

    def __str__(self):
        return f"MultiHVal({self.val} @ {self.pos})"

    def setpos(self, heap: "Heap", pos: int) -> None:
        if pos == -1:
            # Shouldn't really be multiply deleted,
            # but we'll silently swallow any exception.
            try:
                del self.pos[heap]
            except KeyError:
                pass
        else:
            self.pos[heap] = pos

    def getpos(self, heap: "Heap") -> int:
        return self.pos[heap]

    def __lt__(self, other: "MultiHVal") -> bool:
        return self.val < other.val

    def __gt__(self, other: "MultiHVal") -> bool:
        return self.val > other.val


class Heap(typing.Generic[HEType]):
    """
    Heap implements a min or max heap, with most of the code
    stolen from the semi-native Python implementation
    ("import heapq").  However, entries that go *into* the
    heap must be derived from HeapEnt.

    An item *in* the heap can then be modified.  The caller
    that modifies the item must tell us whether its "value" has
    been increased or decreased, which determines the direction
    we need to re-sift the new value.

    Arbitrary items in the heap can also be removed (not just
    the front element).

    The heap is a min-heap if is_min is true during init, or
    a max-heap if not.  Elements need an x < y test for min-heap
    or an x > y test for max-heap.

    See heapq.__about__ (from import heapq).
    """

    def __init__(
        self,
        name: str,
        x: typing.Optional[typing.List[HEType]] = None,
        is_min: bool = True,
    ) -> None:
        self.name = name
        self.is_min = is_min
        self.debug_verbose = False
        self.heap = []  # type: typing.List[HEType]
        if x is not None:
            self.heapify(x)

    def __str__(self) -> str:
        return self.name

    def heapify(self, x: typing.List[HEType]) -> None:
        """
        Transform list x into heap in place.
        Existing heap, if any, is discarded!
        """
        n = len(x)
        for e in self.heap:
            e.setpos(self, -1)

        # Set initial positions.
        self.heap = x
        for i in range(n):
            x[i].setpos(self, i)

        # Transform in place, bottom up.  See heapq.
        if self.is_min:
            sifter = self._siftup_min
        else:
            sifter = self._siftup_max
        for i in reversed(range(n // 2)):
            sifter(i)

    def __len__(self) -> int:
        return len(self.heap)

    def __getitem__(self, i: int) -> HEType:
        return self.heap[i]

    def __iter__(self) -> typing.Iterator:
        return iter(self.heap)

    def push(self, item: HEType) -> None:
        """
        Push item onto heap, maintaining the heap invariant.
        """
        self.heap.append(item)  # must extend the heap
        self._siftdown(0, len(self.heap) - 1, item)

    def pop(self) -> HEType:
        """
        Pop the smallest (or largest, if max-heap) item off the
        heap, maintaining the heap invariant.
        """
        lastelt = self.heap.pop()
        if len(self.heap) == 0:
            ret = lastelt
        else:
            ret = self.heap[0]
            self._siftup(0, lastelt)
        ret.setpos(self, -1)
        return ret

    def remove(self, item: HEType) -> None:
        """
        Caller wants us to remove a specific entry.  Do that,
        fixing the remaining heap.
        """
        pos = item.getpos(self)
        assert self.heap[pos] is item
        item.setpos(self, -1)
        # Remove the last element, as if we were doing a regular
        # heap-pop.  It's possible that the last element is the
        # only element (in which case pos==0) and we are now done.
        # Or, it's possible that item was the last element, in
        # which case pos == len(self.heap).  Note that this
        # also covers the pos==0 case.
        #
        # Otherwise, put the element we removed into the heap
        # at position pos, then fix heap as needed (see fix()).
        lastelt = self.heap.pop()
        if pos < len(self.heap):
            if self.is_min:
                if lastelt < item:
                    self._siftdown(0, pos, lastelt)
                else:
                    self._siftup(pos, lastelt)
            else:
                if lastelt > item:
                    self._siftup(pos, lastelt)
                else:
                    self._siftdown(0, pos, lastelt)

    def pushpop(self, item: HEType):
        """
        Fast version of push followed by pop.  That is, this
        is like replace() except that it includes the necessary
        test, if the heap is nonempty.
        """
        if len(self.heap) > 0:
            r = self.heap[0] < item if self.is_min else self.heap[0] > item
            if r:
                item = self.replace(item)
        return item

    def replace(self, item: HEType) -> HEType:
        """
        Equivalent to calling pop() first, then push(item), but
        more efficient.  Note that because it *is* equivalent to 
        the two-call sequence, it may return an item that sorts
        above (for a min-heap) the to-be-pushed item.  To avoid
        that, test heap[0] first:

            if heap[0] < item:
                item = heap.replace(item)

        See also pushpop().
        """
        ret = self.heap[0]
        ret.setpos(self, -1)
        self._siftup(0, item)
        return ret

    def _siftdown(self, startpos: int, pos: int, newitem: HEType) -> None:
        """
        Fix heap-ness of self.heap when it is a heap at
        all indices >= startpos, except maybe for pos
        itself, which contains newitem (or would contain
        it if it had been written yet: it might have a junk
        item instead).  We simply restore the heap invariant.

        Note: _siftdown always stores newitem and calls setpos,
        after finding the right position, even if the initial
        pos value is the right position.
        """
        compar = newitem.__lt__ if self.is_min else newitem.__gt__
        # Follow the path to the root, moving parents down
        # until newitem fits.  (Note: if items are equal, we
        # leave them in place.)
        while pos > startpos:
            parentpos = (pos - 1) >> 1
            parent = self.heap[parentpos]
            if compar(parent):
                self.heap[pos] = parent
                parent.setpos(self, pos)
                pos = parentpos
                continue
            break
        self.heap[pos] = newitem
        newitem.setpos(self, pos)

    def _siftup(self, pos: int, item: HEType) -> None:
        """
        Store item at pos.

        The child indices of pos are already heaps, and we want
        to make a heap at index pos too.  We do this by bubbling
        the smaller child of pos up (or larger up, if max-heap)
        until hitting a leaf, then using _siftdown to move the
        oddball originally at index pos into place.

        See the standard heapq for why this code is the way it is
        (in particular the reference to the exercise in Knuth vol 3).

        We switch out to the appropriate _siftup, with duplicated
        code, to try to keep the code path short.
        """
        self.heap[pos] = item
        item.setpos(self, pos)
        if self.is_min:
            self._siftup_min(pos)
        else:
            self._siftup_max(pos)

    def _siftup_inplace(self, pos: int) -> None:
        """
        Like _siftup but when item is already in place.
        """
        if self.is_min:
            self._siftup_min(pos)
        else:
            self._siftup_max(pos)

    def _siftup_min(self, pos: int) -> None:
        """
        Internal implementation of _siftup for min-heap: uses e1 < e2.
        """
        endpos = len(self.heap)
        startpos = pos
        newitem = self.heap[pos]
        # Bubble up the smaller child until hitting a leaf.
        childpos = 2 * pos + 1  # leftmost child position
        while childpos < endpos:
            # Set childpos to index of smaller child.
            rightpos = childpos + 1
            if rightpos < endpos and self.heap[rightpos] < self.heap[childpos]:
                childpos = rightpos
            # Move smaller child up.
            c = self.heap[childpos]
            self.heap[pos] = c
            c.setpos(self, pos)
            pos = childpos
            childpos = 2 * pos + 1
        # The leaf at pos is empty now; put newitem there and bubble
        # it up to its final resting place (by sifting its parents down).
        self._siftdown(startpos, pos, newitem)

    def _siftup_max(self, pos: int) -> None:
        """
        Internal implementation of _siftup for max-heap: uses e1 > e2.
        """
        endpos = len(self.heap)
        startpos = pos
        newitem = self.heap[pos]
        # Bubble up the larger child until hitting a leaf.
        childpos = 2 * pos + 1  # leftmost child position
        while childpos < endpos:
            # Set childpos to index of larger child.
            rightpos = childpos + 1
            if rightpos < endpos and self.heap[rightpos] > self.heap[childpos]:
                childpos = rightpos
            # Move larger child up.
            c = self.heap[childpos]
            self.heap[pos] = c
            c.setpos(self, pos)
            pos = childpos
            childpos = 2 * pos + 1
        # The leaf at pos is empty now; put newitem there and bubble
        # it up to its final resting place (by sifting its parents down).
        self._siftdown(startpos, pos, newitem)

    def decreased(self, item: HEType) -> None:
        """
        Caller has decreased the given item.  Fix the heap.
        """
        self.fix_after_delta(item, True)

    def increased(self, item: HEType) -> None:
        """
        Caller has increased the given item.  Fix the heap.
        """
        self.fix_after_delta(item, False)

    def fix_after_delta(self, item: HEType, is_smaller: bool) -> None:
        """
        Caller has modified an existing entry, decreasing or
        increasing it per is_smaller.  Fix the heap.
        """
        pos = item.getpos(self)
        assert self.heap[pos] is item
        # If item got smaller in a min-heap, or bigger in a max-heap,
        # it simply may need to move towards the top of the heap
        # (which we call "down" -- lower indices).
        #
        # If item got bigger in a min-heap, or smaller in a max-heap,
        # it may need to move down towards the bottom (which we call
        # "up" -- higher indices).
        if is_smaller == self.is_min:
            self._siftdown(0, pos, item)
        else:
            self._siftup_inplace(pos)

    def debug_assert(self, verbose: bool = False) -> None:
        """
        Verify that the heap possesses the heap property, i.e.,
        that if it's a min-heap, the smallest element is at the
        top or if it's a max-heap, the largest is at the top, and
        that each sub-heap is also a heap.

        Verify that getpos() on each element returns the right
        position, as well.

        This is exported, but is meant only for debugging.
        """
        self.debug_verbose = verbose
        if verbose:
            print(f'checking "{self}", len={len(self.heap)}')
        if self.is_min:
            self._assert_at(0, self._assert_min)
        else:
            self._assert_at(0, self._assert_max)

    def _assert_at(self, pos: int, check_property: typing.Callable) -> None:
        """
        Verify getpos result and heap property.  See debug_assert()
        and _assert_min and _assert_max below.
        """
        while pos < len(self.heap):
            p = self.heap[pos].getpos(self)
            if pos != p:
                raise AssertionError(f"{self}[{pos}] says it is at {p}")
            # Check property of left and right child if they exist.
            # Recursively, check left and right child themselves if
            # they exist -- but unwind the right recursion into the
            # loop here, which permits debug_assert to not check the
            # initial heap length too.
            c = 2 * pos + 1
            if c < len(self.heap):
                check_property(pos, "left", c)
                self._assert_at(c, check_property)
            c += 1
            if c < len(self.heap):
                check_property(pos, "right", c)
            pos = c

    def _assert_min(self, pos: int, which: str, c: int) -> None:
        """
        Verify for min-heap.  See debug_assert().
        """
        if self.debug_verbose:
            print(f"{self}: {self.heap[pos]} s.b.<= {self.heap[c]}")
        if self.heap[c] < self.heap[pos]:
            raise AssertionError(
                f"bad heap: {self} at {pos}: {self.heap[pos]}, "
                f"vs {which} {c} {self.heap[c]}"
            )

    def _assert_max(self, pos: int, which: str, c: int) -> None:
        """
        Verify for max-heap.  See debug_assert().
        """
        if self.debug_verbose:
            print(f"{self}: {self.heap[pos]} s.b.>= {self.heap[c]}")
        if self.heap[c] > self.heap[pos]:
            raise AssertionError(
                f"bad heap: {self} at {pos}: {self.heap[pos]}, "
                f"vs {which} {c} {self.heap[c]}"
            )


if __name__ == "__main__":
    import argparse
    import random

    def test_empty_heap(verbose):
        h = Heap("empty", is_min=True)
        h.debug_assert(verbose)

    def test_simple_sorted(verbose):
        """
        Test heaps with forward and reverse sorted inputs.
        """
        h = Heap("test_simple_sorted_min", is_min=True)
        for i in range(30):
            h.push(HVal(i))
        h.debug_assert(verbose)
        for i, item in enumerate(h):
            assert i == item.val
        h = Heap("test_simple_sorted_max", is_min=False)
        for i in range(30):
            h.push(HVal(i))
        h.debug_assert(verbose)

    def test_simple_random(verbose):
        h = Heap("test_simple_random (with dups)")
        for i in range(100):
            h.push(HVal(random.randint(0, 29)))
        h.debug_assert(verbose)

    def test_multi_random(verbose):
        h1 = Heap("test_multi_random heap 1")
        h2 = Heap("test_multi_random heap 2")
        for i in range(100):
            e = MultiHVal(random.randint(0, 29))
            where = random.randint(1, 3)
            if (where & 1) != 0:
                h1.push(e)
            if (where & 2) != 0:
                h2.push(e)
        if verbose:
            print(f"lengths: h1 = {len(h1)}, h2 = {len(h2)}")
        # Verbose is too verbose here: we only want the lengths
        h1.debug_assert()
        h2.debug_assert()

    def make_random(n: int, name: str) -> typing.Tuple[Heap, typing.List[HVal]]:
        elts = []
        for i in range(n):
            elts.append(HVal(i))
        random.shuffle(elts)
        h = Heap(name)  # type: Heap[HVal]
        for e in elts:
            h.push(e)
        return h, elts

    def test_adjustments(verbose):
        n = 1000
        h, elts = make_random(n, "test_adjustments")
        # Adjust every element once
        for e in elts:
            # pick a value between 1 and 2n-1
            v = random.randint(1, 2 * n)
            # subtract n so that it's in [-(n+1)..n]
            if v > n:
                v -= 2 * n
            e.val += v
            h.fix_after_delta(e, v < 0)

        h.debug_assert(verbose)

    def test_remove(verbose):
        h, elts = make_random(100, "test_remove")
        for e in elts:
            h.remove(e)
            h.debug_assert(verbose)

    def main():
        """
        Invoke unit tests.
        """
        parser = argparse.ArgumentParser("xheap unit test")
        parser.add_argument("-v", "--verbose", action="store_true")
        args = parser.parse_args()

        test_empty_heap(args.verbose)
        test_simple_sorted(args.verbose)
        test_simple_random(args.verbose)

        test_multi_random(args.verbose)

        test_adjustments(args.verbose)

        test_remove(args.verbose)

    main()
