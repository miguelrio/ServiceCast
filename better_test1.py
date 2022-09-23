from Router import Router

def setup():

    group1 = [

        {'replica': '2',	'delay': 1,	'load': 5,	'result': 'y',	'desc': "best delay, 10 worse load"},
        {'replica': '3',	'delay': 2,	'load': 4,	'result': 'n',	'desc': "9 better load"},
        {'replica': '4',	'delay': 3,	'load': 3,	'result': 'n',	'desc': "9 better both"},
        {'replica': '5',	'delay': 4,	'load': 2,	'result': 'n',	'desc': "9 better delay"},
        {'replica': '6',	'delay': 5,	'load': 1,	'result': 'y',	'desc': "best load"},
        {'replica': '7',	'delay': 6,	'load': 6,	'result': 'n',	'desc': "worst on both"},
        {'replica': '8',	'delay': 4,	'load': 4,	'result': 'n',	'desc': "4, 9 better both"},
        {'replica': '9',	'delay': 2,	'load': 2,	'result': 'y',	'desc': "lower load than 2, lower delay than 6"},
        {'replica': '10',	'delay': 1,	'load': 6,	'result': 'n',	'desc': "2 has lower load"},
        {'replica': '11',	'delay': 1,	'load': 5,	'result': '?',	'desc': "tie break with 2    "}
    ]

    group2 = [
        {'replica': '3',	'delay': 2,	'load': 4,	'result': 'n',	'desc': "9 better load"},
        {'replica': '4',	'delay': 3,	'load': 3,	'result': 'n',	'desc': "9 better both"},
        {'replica': '5',	'delay': 4,	'load': 2,	'result': 'n',	'desc': "9 better delay"},
        {'replica': '6',	'delay': 5,	'load': 1,	'result': 'y',	'desc': "best load"},
        {'replica': '7',	'delay': 6,	'load': 6,	'result': 'n',	'desc': "worst on both"},
        {'replica': '8',	'delay': 4,	'load': 4,	'result': 'n',	'desc': "4, 9 better both"},
        {'replica': '9',	'delay': 2,	'load': 2,	'result': 'y',	'desc': "lower load than 10, lower delay than 6"},
        {'replica': '10',	'delay': 1,	'load': 6,	'result': 'y',	'desc': "best delay"}
    ]

    group3 = [
        {'replica': '2',	'delay': 1,	'load': 5,	'result': 'y',	'desc': "best delay, 10 worse load"},
        {'replica': '3',	'delay': 2,	'load': 4,	'result': 'y',	'desc': "better load than 2"},
        {'replica': '4',	'delay': 3,	'load': 3,	'result': 'y',	'desc': "better load than 2"},
        {'replica': '5',	'delay': 4,	'load': 2,	'result': 'y',	'desc': "better load than 2,8"},
        {'replica': '6',	'delay': 5,	'load': 1,	'result': 'y',	'desc': "best load"},
        {'replica': '7',	'delay': 6,	'load': 6,	'result': 'n',	'desc': "worst on both"},
        {'replica': '8',	'delay': 4,	'load': 4,	'result': 'n',	'desc': "4 better both"},
        {'replica': '10',	'delay': 1,	'load': 6,	'result': 'n',	'desc': "2 has lower load"}
    ]



    r = Router('test')

    # group1
    res1 = r.decide_announcements(group1)
    print("METRIC_TABLE group1")
    print_metric_table(group1)
    print("ANNOUNCEMENTS group1")
    print_metric_table(res1)
    print()


    # group2
    res2 = r.decide_announcements(group2)
    print("METRIC_TABLE group2")
    print_metric_table(group2)
    print("ANNOUNCEMENTS group2")
    print_metric_table(res2)
    print()


    # group3
    res3 = r.decide_announcements(group3)
    print("METRIC_TABLE group3")
    print_metric_table(group3)
    print("ANNOUNCEMENTS group3")
    print_metric_table(res3)

    

# Print metric table
def print_metric_table(metrics_table):
        for metric_no, metric in enumerate(metrics_table):
            print("       {:2d}  {}".format(metric_no+1, metric))
            
    
setup()
