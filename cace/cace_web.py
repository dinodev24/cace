from flask import Flask, render_template, request, Response
from .parameter import ParameterManager
from .web import templates

import argparse
import json
import logging
import mpld3
import os
import sys
import queue

app = Flask(__name__, template_folder='web', static_folder='web/static')


@app.route('/')
def homepage():
    global figures

    # Get all parameter names to put in selection table
    pnames = parameter_manager.get_all_pnames()

    # Clear variables that hold results from previous runs
    parameter_manager.results = {}
    parameter_manager.result_types = {}
    figures = {}
    data = [{'name': pname} for pname in pnames]

    # The web interface also follow's the CLI's debugging options
    return render_template(
        template_name_or_list='index.html', data=data, DEBUG=debug
    )


@app.route('/runsim', methods=['POST'])
def runsim():
    rd = json.loads(request.get_data())

    # Set the variables to default if the value returned is empty
    if rd['max_runs'] == '':
        rd['max_runs'] = None
    if rd['run_path'] == '':
        rd['run_path'] = None
    if rd['jobs'] == '':
        rd['jobs'] = None
    if rd['netlist_source'] == '':
        rd['netlist_source'] = 'best'
    if rd['parallel_parameters'] == '':
        rd['parallel_parameters'] = 4
    logger.debug(rd)

    params = rd['selected_params']

    # Change the parameter manager options
    parameter_manager.max_runs = rd['max_runs']
    parameter_manager.run_path = rd['run_path']
    parameter_manager.jobs = rd['jobs']

    # Don't run anything if no simulations were selected
    # TODO: Do this on the JS side instead
    if len(params) == 0:
        return '', 200

    # Create the directory in the runs directory
    parameter_manager.prepare_run_dir()
    for pname in params:
        parameter_manager.queue_parameter(
            pname=pname,
            start_cb=lambda param, steps: (
                any_queue.put(
                    {
                        'task': 'start',
                        'param': param,
                        'steps': steps,
                    }
                )
            ),
            step_cb=lambda param: (
                any_queue.put({'task': 'step', 'param': param})
            ),
            cancel_cb=lambda param: (
                any_queue.put({'task': 'cancel', 'param': param})
            ),
            end_cb=lambda param: (
                any_queue.put({'task': 'end', 'param': param}),
            ),
        )

    # Use the options from the web interface
    parameter_manager.set_runtime_options('force', rd['force'])
    parameter_manager.set_runtime_options('noplot', rd['noplot'])
    parameter_manager.set_runtime_options('nosim', rd['nosim'])
    parameter_manager.set_runtime_options('sequential', rd['sequential'])
    parameter_manager.set_runtime_options(
        'netlist_source', rd['netlist_source']
    )
    parameter_manager.set_runtime_options(
        'parallel_parameters', rd['parallel_parameters']
    )
    parameter_manager.run_parameters_async()

    # Send the progress tab's HTML data
    any_queue.put(
        {
            'task': 'progress',
            'html': templates.PROGRESS_TEMPLATE.render(params=params),
        }
    )
    return '', 200


def generate_sse():
    datasheet = parameter_manager.datasheet['parameters']

    while True:
        # Get the next task in the queue
        aqg = any_queue.get()

        if aqg['task'] == 'end':
            for i in parameter_manager.running_threads:
                if i.param == aqg['param']:
                    aqg['status'] = i.result_type.name
                    if len(i.plots_dict) > 0:
                        # Store the matplotlib plot for converting to HTML later
                        figures[i.pname] = i.plots_dict
        elif aqg['task'] == 'end_stream':
            logger.debug('ending sse stream')
            break
        if 'param' in aqg:
            aqg['param'] = list(datasheet.keys())[
                list(datasheet.values()).index(aqg['param'])
            ]
        logger.debug('Sending:' + str(aqg))
        yield f'data: {json.dumps(aqg)}\n\n'


@app.route('/stream')
def stream():
    logger.debug('starting sse stream')

    # Starts a stream that is used to send data back in real time
    return Response(generate_sse(), content_type='text/event-stream')


# A general function for receiving and processing data sent from the web interface
@app.route('/receive_data', methods=['POST'])
def receive_data():
    data = request.get_json()
    logger.debug('Received:' + str(data))

    if data['task'] == 'end_stream':
        any_queue.put({'task': 'end_stream'})
    # TODO: Have individual cancel buttons on the web interface
    elif data['task'] == 'cancel_sims':
        parameter_manager.cancel_parameters()
    elif data['task'] == 'fetchresults':
        simresults()
    return '', 200


# Render the HTML for the plots and the result summary
def simresults():
    parameter_manager.join_parameters()
    result = []
    divs = []

    # Parse the markdown output
    summary_lines = parameter_manager.summarize_datasheet().split('\n')[7:-2]
    lengths = {
        param: len(
            list(
                parameter_manager.datasheet['parameters'][param]['spec'].keys()
            )
        )
        for param in parameter_manager.get_all_pnames()
    }
    for param in parameter_manager.get_result_types().keys():
        total = 0
        for i in parameter_manager.get_all_pnames():
            if i == param:
                for j in range(lengths[param]):
                    row = summary_lines[total + j].split('|')
                    result.append(
                        {
                            'parameter_str': row[1],
                            'tool_str': row[2],
                            'result_str': row[3],
                            'min_limit_str': row[4],
                            'min_value_str': row[5],
                            'max_limit_str': row[6],
                            'max_value_str': row[7],
                            'typ_limit_str': row[8],
                            'typ_value_str': row[9],
                            'status_str': row[10],
                        }
                    )

            total += lengths[i]

    divs.append('<br>')

    # Render the previously stored matplotlib plots into HTML
    for pname in figures.keys():
        divs.append(
            f'<details>\n<summary>Figures for {paramkey_paramdisplay[pname]}</summary>'
        )
        for figure in figures[pname]:
            fig = figures[pname][figure].figure
            fig.set_tight_layout(True)
            fig.set_size_inches(fig.get_size_inches() * 1.25)
            # TODO: Put the grid here
            divs.append(
                mpld3.fig_to_html(
                    fig, include_libraries=False, template_type='simple'
                )
            )

        divs.append('</details>\n<br>')

    # Send the results tab to the web interface
    any_queue.put(
        {
            'task': 'results',
            'summary': templates.RESULTS_SUMMARY_TEMPLATE.render(data=result),
            'plots': templates.RESULTS_PLOTS_TEMPLATE.render(divs=divs),
        }
    )
    return 200, ''


@app.before_request
def initialize():
    # Remove the before_request tag since this function is supposed to run only once
    app.before_request_funcs[None].remove(initialize)

    # Restore the stdout back to its original for debugging purposes
    sys.stdout = sys.__stdout__


# The main function for starting the web interface.
def web():
    # This structure is used to send the message to close the stream after quitting
    try:
        # We need the global tags because they are initialized here, but will be used elsewhere
        global debug
        global paramkey_paramdisplay
        global paramdisplay_paramkey
        global parameter_manager
        global any_queue
        global figures
        global logger

        parser = argparse.ArgumentParser(
            prog='cace',
            description="""This is the web interface for CACE.""",
            epilog='Online documentation at: https://cace.readthedocs.io/',
        )
        parser.add_argument(
            '-l',
            '--log-level',
            type=str,
            choices=logging._levelToName.values(),
            default='INFO',
            help="""set the log level for a more fine-grained output""",
        )
        parser.add_argument(
            '--flask-log-level',
            type=str,
            choices=logging._levelToName.values(),
            default='CRITICAL',
            help="""set the log level for flask""",
        )
        parser.add_argument(
            '-d',
            '--debug',
            action='store_true',
            help="""print debugging information""",
        )
        args = parser.parse_args()

        debug = args.debug
        host = 'localhost'
        port = 5000

        # Disable outputs (the access logs) from flask
        log = logging.getLogger('werkzeug')
        log.setLevel(args.flask_log_level)
        logger = logging.getLogger('__cace__')
        logger.setLevel(args.log_level)

        print(
            'Open the CACE web interface at: http://' + host + ':' + str(port)
        )

        # Initialize the parameter manager, lookup tables, queue
        parameter_manager = ParameterManager(
            max_runs=None, run_path=None, jobs=None
        )
        parameter_manager.find_datasheet(os.getcwd(), False)
        paramkey_paramdisplay = {
            i: j.get('display', i)
            for i, j in parameter_manager.datasheet['parameters'].items()
        }
        paramdisplay_paramkey = {
            j.get('display', i): i
            for i, j in parameter_manager.datasheet['parameters'].items()
        }
        any_queue = queue.Queue()

        # This is done to make the startup message from flask disappear
        sys.stdout = open(os.devnull, 'w')
        app.run(debug=debug, host=host, port=port, use_reloader=debug)
    finally:
        any_queue.put({'task': 'close'})
