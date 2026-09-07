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
          'OPEN_CALLBACK': 30, 'ENTRY': 40, 'SIGNAL': 50, 'CLOSE': 60, 'RECORD': 70}


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


def run_streams(streams, *, complete_timestamp=None, funding=None):
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
        batch=[(key,index,event,iterator)]
        if funding is not None and event.phase in ('OPEN_CALLBACK','ENTRY'):
            while heap and heap[0][0][0]==key[0] and heap[0][2].phase in ('OPEN_CALLBACK','ENTRY'):
                batch.append(heapq.heappop(heap))
            funding.run_callbacks([item[2] for item in batch])
        else:
            event.callback()
        for item_key,item_index,item_event,item_iterator in batch:
            trace.append({'timestamp':item_key[0], 'phase':item_event.phase, 'strategy':item_event.strategy, 'identity':item_event.identity})
            push(item_index,item_iterator)
        if complete_timestamp is not None and (not heap or heap[0][0][0] != key[0]):
            complete_timestamp(key[0])
    return trace
