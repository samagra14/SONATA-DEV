#!/usr/bin/env python
#  Author:
#  Arpit Gupta (arpitg@cs.princeton.edu)

import pickle
import time
import datetime
import math
import json
import os

from sonata.query_engine.sonata_queries import *
from sonata.core.training.utils import create_spark_context
from sonata.core.integration import Target
from sonata.core.refinement import get_refined_query_id, Refinement
from sonata.core.training.hypothesis.hypothesis import Hypothesis
from sonata.system_config import BASIC_HEADERS
from sonata.core.utils import dump_rdd, load_rdd, TMP_PATH, parse_log_line

"""
Schema:
ts,sIP,sPort,dIP,dPort,nBytes,proto,tcp.seq,tcp.ack,tcp.flags
"""


def get_training_query(sc, flows_File, qid):
    q = None
    training_data = None

    T = 1  # T = 1 ==> 1 second window

    if qid == 1:
        # dupacks
        training_data = (sc.textFile(flows_File)
                         .map(parse_log_line)
                         .map(lambda s: tuple([1] + (list(s[1:]))))
                         .filter(lambda (ts, sIP, sPort, dIP, dPort, nBytes, proto, tcp_seq, tcp_ack,
                                        tcp_flags): str(proto) == '6' and str(tcp_flags) == '16')
                         # .filter(lambda s: ((str(IPNetwork(str(str(s[3])+"/8")).network)) == '185.0.0.0'
                         #                    or (str(IPNetwork(str(str(s[3])+"/8")).network)) == '37.0.0.0'
                         #                    or (str(IPNetwork(str(str(s[3])+"/8")).network)) == '45.0.0.0'
                         #                    or (str(IPNetwork(str(str(s[3])+"/8")).network)) == '64.0.0.0'
                         #                    or (str(IPNetwork(str(str(s[3])+"/8")).network)) == '66.0.0.0'
                         #                    or (str(IPNetwork(str(str(s[3])+"/8")).network)) == '108.0.0.0'
                         #                    or (str(IPNetwork(str(str(s[3])+"/8")).network)) == '198.0.0.0'
                         #                    or (str(IPNetwork(str(str(s[3])+"/8")).network)) == '192.0.0.0'
                         #                    or (str(IPNetwork(str(str(s[3])+"/8")).network)) == '208.0.0.0'
                         #                    )
                         #         )
                         )

        q = (PacketStream(qid)
             .map(keys=('ipv4_dstIP', 'ipv4_srcIP', 'tcp_ack'), map_values=('count',), func=('eq', 1,))
             .reduce(keys=('ipv4_dstIP', 'ipv4_srcIP', 'tcp_ack'), func=('sum',))
             .filter(filter_vals=('count',), func=('geq', '99.99'))
             )

    elif qid == 2:
        # number new connections
        training_data = (sc.textFile(flows_File)
                         .map(parse_log_line)
                         .map(lambda s: tuple([1] + (list(s[1:]))))
                         .filter(lambda (ts, sIP, sPort, dIP, dPort, nBytes, proto, tcp_seq, tcp_ack,
                                        tcp_flags): str(proto) == '6' and str(tcp_flags) == '2')
                         )

        q = (PacketStream(qid)
             .map(keys=('ipv4_dstIP',), map_values=('count',), func=('eq', 1,))
             .reduce(keys=('ipv4_dstIP',), func=('sum',))
             .filter(filter_vals=('count',), func=('geq', '99.9'))
             )

    elif qid == 3:
        # ssh bruteforce
        training_data = (sc.textFile(flows_File)
                         .map(parse_log_line)
                         .map(lambda s: tuple([1] + (list(s[1:]))))
                         .filter(lambda (ts, sIP, sPort, dIP, dPort, nBytes, proto, tcp_seq, tcp_ack,
                                        tcp_flags): str(proto) == '6')
                         .filter(lambda (ts, sIP, sPort, dIP, dPort, nBytes, proto, tcp_seq, tcp_ack,
                                        tcp_flags): str(dPort) == '22')
                         .map(lambda (ts, sIP, sPort, dIP, dPort, nBytes, proto, tcp_seq, tcp_ack,
                                     tcp_flags): (ts, sIP, sPort, dIP, dPort,
                                                  100 * math.ceil(float(nBytes) / 100),
                                                  proto, tcp_seq, tcp_ack, tcp_flags))
                         )

        q = (PacketStream(qid)
             .map(keys=('ipv4_dstIP', 'ipv4_srcIP', 'nBytes'))
             .distinct(keys=('ipv4_dstIP', 'ipv4_srcIP', 'nBytes'))
             .map(keys=('ipv4_dstIP', 'nBytes',), map_values=('count',), func=('eq', 1,))
             .reduce(keys=('ipv4_dstIP', 'nBytes',), func=('sum',))
             .filter(filter_vals=('count',), func=('geq', '99.9'))
             )

    elif qid == 4:
        # heavy hitter
        training_data = (sc.textFile(flows_File)
                         .map(parse_log_line)
                         .map(lambda s: tuple([1] + (list(s[1:]))))
                         .filter(lambda (ts, sIP, sPort, dIP, dPort, nBytes, proto, tcp_seq, tcp_ack,
                                        tcp_flags): str(proto) == '6')
                         .map(lambda (ts, sIP, sPort, dIP, dPort, nBytes, proto, tcp_seq, tcp_ack,
                                     tcp_flags): (ts, sIP, sPort, dIP, dPort,
                                                  int(nBytes),
                                                  proto, tcp_seq, tcp_ack, tcp_flags))
                         )

        q = (PacketStream(qid)
             .map(keys=('ipv4_dstIP', 'ipv4_srcIP', 'nBytes'))
             .map(keys=('ipv4_dstIP', 'ipv4_srcIP'), values=('nBytes',))
             .reduce(keys=('ipv4_dstIP', 'ipv4_srcIP',), func=('sum',))
             .filter(filter_vals=('nBytes',), func=('geq', '99.9'))
             )

    elif qid == 5:
        # super spreader
        training_data = (sc.textFile(flows_File)
                         .map(parse_log_line)
                         .map(lambda s: tuple([1] + (list(s[1:]))))
                         )

        q = (PacketStream(qid)
             .map(keys=('ipv4_dstIP', 'ipv4_srcIP'))
             .distinct(keys=('ipv4_dstIP', 'ipv4_srcIP'))
             .map(keys=('ipv4_srcIP',), map_values=('count',), func=('eq', 1,))
             .reduce(keys=('ipv4_srcIP',), func=('sum',))
             .filter(filter_vals=('count',), func=('geq', '99.99'))
             )

    elif qid == 6:
        # port scan
        training_data = (sc.textFile(flows_File)
                         .map(parse_log_line)
                         .map(lambda s: tuple([1] + (list(s[1:]))))
                         )

        q = (PacketStream(qid)
             .map(keys=('ipv4_srcIP', 'dPort'))
             .distinct(keys=('ipv4_srcIP', 'dPort'))
             .map(keys=('ipv4_srcIP',), map_values=('count',), func=('eq', 1,))
             .reduce(keys=('ipv4_srcIP',), func=('sum',))
             .filter(filter_vals=('count',), func=('geq', '99.99'))
             )

    elif qid == 7:
        # udp ddos
        training_data = (sc.textFile(flows_File)
                         .map(parse_log_line)
                         # .map(lambda s: tuple([int(math.ceil(int(s[0]) / T))] + (list(s[1:]))))
                         .map(lambda s: tuple([1] + (list(s[1:]))))
                         .filter(lambda (ts, sIP, sPort, dIP, dPort, nBytes, proto, tcp_seq, tcp_ack,
                                        tcp_flags): str(proto) == '17')
                         )

        q = (PacketStream(qid)
             .map(keys=('ipv4_dstIP', 'ipv4_srcIP'))
             .distinct(keys=('ipv4_dstIP', 'ipv4_srcIP'))
             .map(keys=('ipv4_dstIP',), map_values=('count',), func=('eq', 1,))
             .reduce(keys=('ipv4_dstIP',), func=('sum',))
             .filter(filter_vals=('count',), func=('geq', '99.9'))
             # .map(keys=('ipv4_dstIP',))
             )

    elif qid == 11:
        # UDP traffic asymmetry
        training_data = (sc.textFile(flows_File)
                         .map(parse_log_line)
                         # .map(lambda s: tuple([int(math.ceil(int(s[0]) / T))] + (list(s[1:]))))
                         .map(lambda s: tuple([1] + (list(s[1:]))))
                         .filter(lambda (ts, sIP, sPort, dIP, dPort, nBytes, proto, tcp_seq, tcp_ack,
                                        tcp_flags): str(proto) == '17')
                         )
        q1 = (PacketStream(111)
              .map(keys=('ipv4_dstIP','sPort'))
              .reduce(keys=('ipv4_dstIP','sPort',), func=('sum',))
              .filter(filter_vals=('count1',), func=('geq', '99.9'))
              )
        q2 = (PacketStream(112)
              .map(keys=('ipv4_srcIP','dPort'))
              .reduce(keys=('ipv4_srcIP','dPort',), func=('sum',))
              .map(keys=('ipv4_srcIP','dPort'), values=('count2',))
              )

        q = (q1
             .join(query=q2, new_qid=113)
             .map(keys=('ipv4_dstIP','sPort'), map_values=('count3'), func=('diff', 1,))
             .filter(filter_vals=('count3',), func=('geq', '99.9'))
             )



    q.basic_headers = BASIC_HEADERS

    return q, training_data


def generate_counts_and_costs():
    # TD_PATH = '/mnt/dirAB.out_00000_20160121080100.transformed.csv/part-00000'
    # TD_PATH = '/mnt/dirAB.out_00000_20160121080100.transformed.csv'

    TD_PATH = '/mnt/caida_20160121080147_transformed'

    baseDir = os.path.join(TD_PATH)
    flows_File = os.path.join(baseDir, '*.csv')
    # flows_File = TD_PATH

    qids = [1, 2, 3, 4, 5, 6, 7]
    sc = create_spark_context()

    with open('sonata/config.json') as json_data_file:
        data = json.load(json_data_file)

    conf = data["on_server"][data["is_on_server"]]["sonata"]
    refinement_keys = conf["refinement_keys"]
    print "Possible Refinement Keys", refinement_keys

    target = Target()

    for qid in qids:
        # clean the tmp directory before running the experiment
        clean_cmd = "rm -rf " + TMP_PATH + "*"
        # print "Running command", clean_cmd
        os.system(clean_cmd)

        # get query and query-specific training data
        query, training_data = get_training_query(sc, flows_File, qid)
        refinement_object = Refinement(query, target, refinement_keys, sc)

        # print "Collecting the training data for the first time ...", training_data_fname.take(2)
        training_data_fname = "training_data"
        dump_rdd(training_data_fname, training_data)

        # training_data_fname = sc.parallelize(training_data_fname.collect())
        print "Collecting timestamps for the experiment ..."
        timestamps = load_rdd(training_data_fname, sc).map(lambda s: s[0]).distinct().collect()
        print "#Timestamps: ", len(timestamps)

        refinement_object.update_filter(training_data_fname)

        hypothesis = Hypothesis(query, sc, training_data_fname, timestamps, refinement_object, target)


if __name__ == '__main__':
    generate_counts_and_costs()