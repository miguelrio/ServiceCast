from Router import Router
from Verbose import Verbose
import simpy

Verbose.level = 2

env = simpy.Environment()

r1 = Router(1, env)

# define test entry sets

entries1 = [
    { 'load': 0, 'delay': 4, 'replica': 's1', 'announce': False },
    { 'load': 0, 'delay': 3, 'replica': 's1', 'announce': True },
    { 'load': 2, 'delay': 3, 'replica': 's1', 'announce': False }
]

entries2 = [
    { 'load': 0, 'delay': 4, 'replica': 's1', 'announce': True },
    { 'load': 1, 'delay': 3, 'replica': 's1', 'announce': True }
]


# from the google doc
entries_google_doc = [
    { 'load': 3, 'delay': 20, 'replica': 's1', 'announce': True },
    { 'load': 2, 'delay': 30, 'replica': 's2', 'announce': True  },
    { 'load': 1, 'delay': 40, 'replica': 's3', 'announce': True  },
    { 'load': 100, 'delay': 100, 'replica': 's4', 'announce': False },
    { 'load': 101, 'delay': 99, 'replica': 's5', 'announce': False },
    { 'load': 200, 'delay': 98, 'replica': 's6', 'announce': False },
    { 'load': 1, 'delay': 40, 'replica': 's3', 'announce': True  },
    { 'load': 2, 'delay': 99, 'replica': 's7', 'announce': False },
    { 'load': 2.5, 'delay': 35, 'replica': 's8', 'announce': False },
    { 'load': 3, 'delay': 21, 'replica': 's1', 'announce': True }
]


entries4 = [
    { 'load': 0, 'delay': 4, 'replica': 's1', 'announce': True },
    { 'load': 0, 'delay': 4, 'replica': 's1', 'announce': True },
    { 'load': 0, 'delay': 4, 'replica': 's1', 'announce': True },
    { 'load': 0, 'delay': 4, 'replica': 's1', 'announce': True },
    { 'load': 0, 'delay': 4, 'replica': 's1', 'announce': True }
]

# test decide_announcements() against entry sets

print("entries1")    
ann1 = r1.decide_announcements(entries1)
print("ANNOUNCE {}".format(str(ann1)))


print("entries2")    
ann2 = r1.decide_announcements(entries2)
print("ANNOUNCE {}".format(str(ann2)))


print("entries_google_doc")    
ann_gd = r1.decide_announcements(entries_google_doc)
print("ANNOUNCE {}".format(str(ann_gd)))

print("entries4")    
ann_gd = r1.decide_announcements(entries4)
print("ANNOUNCE {}".format(str(ann_gd)))
