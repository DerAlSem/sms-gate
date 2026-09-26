"""The route ladder: what carries an outbound message, in what order, and what a rung
may conclude.

`routes` holds the vocabulary, `classes` the classifier, `route` the interface every rung
implements, `ladder` the ordered offer, and `dispatch` the single entry point every path
that creates an outbound message goes through.
"""
