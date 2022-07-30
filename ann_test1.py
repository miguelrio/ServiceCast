from Router import Router
from Verbose import Verbose
import simpy

Verbose.level = 2

env = simpy.Environment()

r1 = Router(1, env)

# define test entry sets

entries1 = [
    { 'load': 0, 'delay': 4, 'replica': 's1' },
    { 'load': 0, 'delay': 3, 'replica': 's1' },
    { 'load': 2, 'delay': 3, 'replica': 's1' }
]

entries2 = [
    { 'load': 0, 'delay': 4, 'replica': 's1' },
    { 'load': 1, 'delay': 3, 'replica': 's1' }
]


entries_google_doc = [
    { 'load': 3, 'delay': 20, 'replica': 's1' },
    { 'load': 2, 'delay': 30, 'replica': 's2' },
    { 'load': 1, 'delay': 40, 'replica': 'r3' },
    { 'load': 100, 'delay': 100, 'replica': 'r4' },
    { 'load': 101, 'delay': 99, 'replica': 'r5' },
    { 'load': 200, 'delay': 98, 'replica': 'r6' },
    { 'load': 2, 'delay': 99, 'replica': 'r7' },
    { 'load': 2.5, 'delay': 35, 'replica': 'r8' }
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

