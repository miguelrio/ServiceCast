class Verbose:
    # Class variable
    # Logging levels -- each level prints everything the level below prints:
    #   -2  silent: nothing per event, no ground-truth calculations
    #   -1  metrics: parameter header, per-request lines (OUTCOME_GAP,
    #       DECISION_GAP, STALENESS_ERR, REQUEST_NOT_FORWARDED, BLOCKED) and
    #       end-of-run SUMMARY_ counts (Network.print_metrics_summary)
    #    0  + per-update lines (PACKET_CREATED, RECV_PACKET)
    #    1  + FIB stability lines and other decision detail
    #   2+  + progressively more debug detail
    # Use -1 for large networks and long runs (the log grows with requests,
    # not update messages). Levels 0 and up are for detailed protocol
    # debugging on small networks or short runs: they print every update
    # message, and the logs get far too large otherwise. See doc/Logging.md.
    level = 1

    # If table == 0, print tables simply on one line
    # If table == 1, try and print tables one row per line
    table = 0
