"""Single chronological callback dispatcher, preserving native event clocks.

Streams describe checkpoints, never accepted trades. Callbacks read and mutate
funded account state when dispatched. No outcome policies are enabled here.
"""
from dataclasses import dataclass, field
import heapq
from typing import Callable
import pandas as pd

# Exits are ahead of entries. Marks are only made by the owning native callback
# using information legal at that clock. Native row priority stays in adapters.
PHASES = {'BOUNDARY': 0, 'ACTION': 10, 'PREPARE': 15, 'EXIT': 20,
          'OPEN_CALLBACK': 30, 'ENTRY': 40, 'SIGNAL': 50, 'CLOSE': 60}


@dataclass
class Event:
    when: object
    phase: str
    strategy: str
    identity: str
    callback: Callable = field(repr=False)

    @property
    def key(self):
        ts = pd.Timestamp(self.when)
        if pd.isna(ts) or self.phase not in PHASES:
            raise ValueError('invalid scheduler timestamp/phase')
        return (ts, PHASES[self.phase], self.strategy, self.identity)


def run_streams(streams):
    """Merge sorted lazy adapters. Advance only after each callback completes."""
    heap, previous, seen, trace = [], {}, set(), []
    def push(index, iterator):
        event = next(iterator, None)
        if event is None:
            return
        key = event.key
        if index in previous and key <= previous[index]:
            raise ValueError('adapter chronology/duplicate event failure')
        if key in seen:
            raise ValueError('duplicate scheduler event')
        previous[index] = key
        seen.add(key)
        heapq.heappush(heap, (key, index, event, iterator))
    for index, stream in enumerate(streams):
        push(index, iter(stream))
    while heap:
        key, index, event, iterator = heapq.heappop(heap)
        event.callback()
        trace.append({'timestamp':key[0], 'phase':event.phase, 'strategy':event.strategy, 'identity':event.identity})
        push(index, iterator)
    return trace
