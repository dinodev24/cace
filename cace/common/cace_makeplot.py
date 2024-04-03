#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# cace_makeplot.py
# -----------------------------------------------------------------------------
# Plot routines for CACE using matplotlib
# -----------------------------------------------------------------------------

import re
import os
import copy
import matplotlib

from matplotlib.figure import Figure

# Warning: PIL Tk required, may not be in default install of python3.
# For Fedora, for example, need "yum install python-pillow-tk"

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.backends.backend_agg import FigureCanvasAgg

from .cace_gensim import twos_comp
from .cace_collate import addnewresult
from .spiceunits import spice_unit_unconvert

# -----------------------------------------------------------------------------
# Given a plot record from a spec sheet and a full set of testbenches, generate
# a plot.  The name of the plot file and the vectors to plot, labels, legends,
# and so forth are all contained in the 'plotrec' dictionary.
#
# If run from a GUI then "parent" is a window passed by the caller that the
# plot will be drawn in.
#
# Returns the canvas record generated by matplotlib.
# -----------------------------------------------------------------------------


def cace_makeplot(dsheet, param, parent=None):

    # Regular expression for identifying digital values
    binrex = re.compile(r'([0-9]*)\'([bodh])', re.IGNORECASE)

    if 'plot' not in param:
        return None
    else:
        plotrec = param['plot']

    if 'variables' not in param:
        variables = []
    else:
        variables = param['variables']

    if 'runtime_options' in dsheet:
        runtime_options = dsheet['runtime_options']
    else:
        runtime_options = None

    debug = False
    if runtime_options:
        if 'noplot' in runtime_options:
            if runtime_options['noplot']:
                return None
        if 'debug' in runtime_options:
            debug = runtime_options['debug']

    # The 'format' record of the 'simulate' dictionary in the parameter
    # indicates how the simulation data should be formatted.  The first
    # two items describe how to read the file and are discarded.  The
    # routine that reads the simulation data always moves the "result"
    # entry to the 1st position, so the format needs to be adjusted
    # accordingly.

    simdict = copy.deepcopy(param['simulate'])
    if 'format' in simdict:
        simformat = simdict['format'][2:]
        if 'result' in simformat:
            ridx = simformat.index('result')
            if ridx != 0:
                simformat.insert(0, simformat.pop(simformat.index('result')))
    else:
        simformat = ['result']

    if 'type' in plotrec:
        plottype = plotrec['type']
    else:
        plottype = 'xyplot'

    if plottype == 'histogram':
        xname = 'result'
    else:
        xname = plotrec['xaxis']

    # Organize data into plot lines according to formatting
    # Because the data may get rearranged, create a copy of all testbench
    # results and reference only the copied data.
    tbdata = copy.deepcopy(param['testbenches'])

    numtbs = len(tbdata)
    if numtbs == 0:
        print('Error:  Plot has no results.')

    # All testbenches should have results in the same format.  Use only the
    # first testbench to determine which column of results represents the
    # plot's x-axis data.

    zerotb = tbdata[0]
    results = zerotb['results']
    conditions = zerotb['conditions']

    # In case results[] is not a vector. . .  This should have been handled
    # outside of cace_makeplot and probably needs to be fixed.

    if not isinstance(results[0], list):
        for i in range(len(results)):
            result = results[i]
            if not isinstance(result, list):
                results[i] = [result]

    # Find index of X data in results.  All results lines have the same
    # data, so pick up the number of items per result from the 1st entry.

    rlen = len(results[0])
    try:
        xidx = next(r for r in range(rlen) if simformat[r] == xname)
    except StopIteration:

        if debug:
            print('Refactoring testbench data for plot vs. ' + xname)

        # x-axis variable is not in the variable list.  If it exists as
        # a testbench condition and varies over the testbenches, then
        # add a column to each row of results to represent the variable,
        # and then reorganize the testbenches.

        notfound = True
        for cond in conditions:
            if cond[0] == xname:
                condvalue = cond[2]
                notfound = False
                break

        if notfound:
            print('Plot error:  No signal ' + xname + ' recorded in format.')
            return None

        # For each testbench, add the x-axis condition value to to the results.
        # Also create a string representation of all condition values except
        # the x-axis condition for each testbench, and save it.

        for tbidx in range(0, numtbs):
            thistb = tbdata[tbidx]
            tbresults = thistb['results']
            conditions = thistb['conditions']
            condstr = ''
            for cond in conditions:
                if cond[0] == xname:
                    condvalue = cond[2]
                else:
                    condstr += cond[2]
            thistb['condstr'] = condstr
            newtbresults = []
            for result in tbresults:
                if isinstance(result, list):
                    newresult = result
                else:
                    newresult = [result]
                newresult.append(condvalue)
                newtbresults.append(newresult)
            thistb['results'] = newtbresults

        # For each testbench, find all other testbenches that have the same
        # conditions *except* for the x-axis condition, and combine them
        # into one testbench

        for tbidx in range(0, numtbs):
            thistb = tbdata[tbidx]
            condstr = thistb['condstr']
            for tbcomp in range(tbidx + 1, numtbs):
                comptb = tbdata[tbcomp]
                if 'killed' in comptb:
                    continue
                compstr = comptb['condstr']
                if compstr == condstr:
                    thistb['results'].extend(comptb['results'])
                    comptb['killed'] = True

        # Generate new set of testbenches from the combined set.
        newtbdata = []
        for tbidx in range(0, numtbs):
            thistb = tbdata[tbidx]
            if not 'killed' in thistb:
                newtbdata.append(thistb)

        # Replace the old testbench data
        tbdata = newtbdata

        # Adjust the testbench count and the length of results, the
        # index of the X-axis variable, and the simformat list.

        numtbs = len(tbdata)
        rlen = len(results[0])
        xidx = rlen - 1
        simformat.append(xname)

    if debug:
        print('Processing ' + str(rlen) + ' plot variables.')

    # Redefine "results" and "conditions" after refactoring.
    zerotb = tbdata[0]
    results = zerotb['results']
    conditions = zerotb['conditions']

    # Find unique values of each variable (except results, traces, and iterations)
    # Collect the records of everything being plotted.

    binconv = []
    tracedicts = []
    traces = []
    residx = 0
    for i in range(0, rlen):
        if i != xidx:
            # Keep track of which indexes have traces (i.e., not the X axis values)
            traces.append(i)
        try:
            varrec = next(
                item for item in variables if item['name'] == simformat[i]
            )
        except StopIteration:
            if simformat[i] == 'result':
                varrec = {}
                varrec['name'] = 'result'
                if 'unit' in param:
                    varrec['unit'] = param['unit']
                residx = i
            else:
                varrec = {}

        tracedicts.append(varrec)

        # Mark which items need converting from digital.  Format is verilog-like.
        # Use a format width that is larger than the actual number of digits to
        # force unsigned conversion.

        if 'name' in varrec:
            varname = varrec['name']
        else:
            varname = conditions[i][0]

        bmatch = binrex.match(varname)
        if bmatch:
            digits = bmatch.group(1)
            if digits == '':
                digits = len(results[0][i])
            else:
                digits = int(digits)
            cbase = bmatch.group(2)
            if cbase == 'b':
                base = 2
            elif cbase == 'o':
                base = 8
            elif cbase == 'd':
                base = 10
            else:
                base = 16
            binconv.append([base, digits])
        else:
            binconv.append([])

    needconvert = False
    if xname.split('|')[0] == 'digital' or binconv[xidx] != []:
        needconvert = True

    # Limit the amount of data being processed.  NOTE:  This is a stupid-simple
    # way to do it and it needs much better handling;  e.g., import scipy and
    # resample to a constant time step.

    numpoints = len(results)
    if debug:
        print('Processing ' + str(numpoints) + ' data points.')
    if numpoints > 1000:
        stepsize = int(numpoints / 1000)
        if debug:
            print('Truncating data with step size ' + str(stepsize))
    else:
        stepsize = 1

    # Find which conditions are variable;  conditions which are constant do
    # not need to be displayed in the plot key.  Make a list "stepped" which
    # is True for each condition that is not constant.  If any condition is
    # stepped, then a legend is created for the plot.  Ignore a condition if
    # it is the x-axis condition.

    tracelegend = False
    stepped = []
    for cidx in range(0, len(conditions)):
        stepped.append(False)
        cond = conditions[cidx][2]
        # If condition has been set as the x-axis variable, then it is no
        # longer a stepped condition.
        if conditions[cidx][0] == xname:
            continue
        for tbidx in range(0, numtbs):
            testtb = tbdata[tbidx]
            tbcond = testtb['conditions'][cidx][2]
            if tbcond != cond:
                stepped[cidx] = True
                tracelegend = True
                break

    if debug:
        print('Stepped conditions are: ')
        stepcond = []
        for j in range(0, len(stepped)):
            if j == True:
                stepcond.append(conditions[j][0])
        print('    ' + ' '.join(stepcond))

    # Now plot the result from each testbench.  Each plot ends up as a
    # dictionary entry "pdict" in a larger dictionary "pdata".  Each entry
    # in "pdata" (i.e., each plot trace) is indexed by the list of variable
    # conditions comprising that trace.  This index becomes the text in the
    # plot's legend to identify each trace.

    # Warning:  The existing code does not differentiate between plot traces
    # that are stepped conditions vs. plot traces that are variables.  In
    # general, the variables should not be assumed to have any relationship
    # to each other;  one might be a voltage and another current.  They
    # should be placed in separate sub-graphs.

    pdata = {}

    # Collect results.  Make a separate record for each unique set of stepped
    # conditions encountered.  Record has (X, Y) vector and a list of conditions.

    for tbidx in range(0, numtbs):

        thistb = tbdata[tbidx]
        if tbidx > 0:
            results = thistb['results']
            conditions = thistb['conditions']

            # In case results[] is not a vector. . .  This should have been handled
            # outside of cace_makeplot and probably needs to be fixed.

            if not isinstance(results[0], list):
                for i in range(len(results)):
                    result = results[i]
                    if not isinstance(result, list):
                        results[i] = [result]

        # Create a key index from the list of variable conditions.
        # Also create the corresponding text for the plot legend

        klist = []
        slist = []
        for i in range(0, len(conditions)):
            if stepped[i] == True:
                klist.append(conditions[i][2])
                slist.append(
                    conditions[i][0]
                    + '='
                    + str(conditions[i][2])
                    + conditions[i][1]
                )
        dkey = ','.join(klist)
        stextlist = ' '.join(slist)

        # An empty string seems to work for a key?  But give it a real name.
        if dkey == '':
            dkey = 'default'

        # Diagnostic for debugging
        if debug:
            print('Testbench ' + str(tbidx) + ' key = ' + dkey)
            print('Testbench ' + str(tbidx) + ' legend = "' + stextlist + '"')

        # Collect results from this testbench into a plot trace

        pdict = {}
        pdata[dkey] = pdict

        pdict['xdata'] = []
        pdict['sdata'] = stextlist

        # Each variable (trace) forms a separate trace in this plot.
        # (See note above)

        for i in traces:
            aname = 'ydata' + str(i)
            pdict[aname] = []
            alabel = 'ylabel' + str(i)

            # Get the name of the trace.
            tracedict = tracedicts[i]
            if 'display' in tracedict:
                tracename = tracedict['display']
            else:
                tracename = tracedict['name']

            # Get the units of the trace
            if 'unit' in tracedict:
                if not binrex.match(tracedict['unit']):
                    tracename += ' (' + tracedict['unit'] + ')'

            pdict[alabel] = tracename

        # Now, for each entry in results, add an (X, Y) point to each
        # plot trace.

        for idx in range(0, numpoints, stepsize):
            item = results[idx]

            if needconvert:
                base = binconv[xidx][0]
                digits = binconv[xidx][1]
                # Recast binary strings as integers
                # Watch for strings that have been cast to floats
                # (need to find the source of this)
                if '.' in item[xidx]:
                    item[xidx] = item[xidx].split('.')[0]
                a = int(item[xidx], base)
                b = twos_comp(a, digits)
                xvalue = b
            else:
                xvalue = item[xidx]

            try:
                xfloat = float(xvalue)
            except:
                pdict['xdata'].append(xvalue)
            else:
                pdict['xdata'].append(xfloat)

            for i in traces:
                tracedict = tracedicts[i]
                # For each trace, convert the value from digital to integer if needed
                if binconv[i] != []:
                    base = binconv[i][0]
                    digits = binconv[i][1]
                    a = int(item[i], base)
                    b = twos_comp(a, digits)
                    yvalue = b
                else:
                    yvalue = item[i]

                aname = 'ydata' + str(i)
                try:
                    yfloat = float(yvalue)
                except:
                    pdict[aname].append(yvalue)
                else:
                    if 'unit' in tracedict:
                        yscaled = spice_unit_unconvert(
                            [tracedict['unit'], yfloat]
                        )
                        pdict[aname].append(yscaled)
                    else:
                        pdict[aname].append(yfloat)

    # NOTE:  Loop over testbenches (tbidx) ends here

    fig = Figure()
    if parent == None:
        canvas = FigureCanvasAgg(fig)
    else:
        canvas = FigureCanvasTkAgg(fig, parent)

    # With no parent, just make one plot and put the legend off to the side.  The
    # 'extra artists' capability of print_figure will take care of the bounding box.
    # For display, prepare two subplots so that the legend takes up the space of the
    # second one.

    if parent == None:
        ax = fig.add_subplot(111)
    else:
        ax = fig.add_subplot(121)

    # fig.hold(True)
    for record in pdata:
        pdict = pdata[record]

        # Check if xdata is numeric
        try:
            test = float(pdict['xdata'][0])
        except ValueError:
            numeric = False
            xdata = [i for i in range(len(pdict['xdata']))]
        else:
            numeric = True
            xdata = list(map(float, pdict['xdata']))

        if plottype == 'histogram':
            ax.hist(
                xdata,
                histtype='barstacked',
                label=pdict['sdata'],
                stacked=True,
            )
        elif plottype == 'semilogx':
            for i in traces:
                aname = 'ydata' + str(i)
                alabl = 'ylabel' + str(i)
                ax.semilogx(
                    xdata,
                    pdict[aname],
                    label=pdict['sdata'],
                )
        elif plottype == 'semilogy':
            for i in traces:
                aname = 'ydata' + str(i)
                alabl = 'ylabel' + str(i)
                ax.semilogy(
                    xdata,
                    pdict[aname],
                    label=pdict['sdata'],
                )
        elif plottype == 'loglog':
            for i in traces:
                aname = 'ydata' + str(i)
                alabl = 'ylabel' + str(i)
                ax.loglog(
                    xdata,
                    pdict[aname],
                    label=pdict['sdata'],
                )
        else:
            # plottype is 'xyplot'
            for i in traces:
                aname = 'ydata' + str(i)
                alabl = 'ylabel' + str(i)
                ax.plot(
                    xdata,
                    pdict[aname],
                    label=pdict['sdata'],
                )

        if not numeric:
            ax.set_xticks(xdata)
            ax.set_xticklabels(pdict['xdata'])

    # Automatically generate X axis label if not given alternate text

    tracerec = tracedicts[xidx]
    if 'xlabel' in plotrec:
        xtext = plotrec['xlabel']
    else:
        xtext = tracerec['name']
    if 'unit' in tracerec:
        xtext += ' (' + tracerec['unit'] + ')'
    ax.set_xlabel(xtext)

    # Automatically generate Y axis label if not given alternate text

    tracerec = tracedicts[residx]
    if 'ylabel' in plotrec:
        ytext = plotrec['ylabel']
    else:
        ytext = tracerec['name']
    if 'unit' in tracerec:
        ytext += ' (' + tracerec['unit'] + ')'
    ax.set_ylabel(ytext)

    ax.grid(True)
    if tracelegend:
        legend = ax.legend(loc=2, bbox_to_anchor=(1.05, 1), borderaxespad=0.0)
    else:
        legend = None

    if legend:
        legend.set_draggable(True)

    if parent == None:
        paths = dsheet['paths']
        if 'plots' in paths:
            plotdir = paths['plots']
        else:
            plotdir = paths['simulation']

        netlist_source = runtime_options['netlist_source']

        if 'filename' in plotrec:
            plotname = plotrec['filename']
        else:
            plotname = param['name'] + '.png'

        filepath = os.path.join(plotdir, netlist_source)
        if not os.path.isdir(filepath):
            os.makedirs(filepath)

        filename = os.path.join(plotdir, netlist_source, plotname)

        # NOTE: print_figure only makes use of bbox_extra_artists if
        # bbox_inches is set to 'tight'.  This forces a two-pass method
        # that calculates the real maximum bounds of the figure.  Otherwise
        # the legend gets clipped.
        if legend:
            canvas.print_figure(
                filename, bbox_inches='tight', bbox_extra_artists=[legend]
            )
        else:
            canvas.print_figure(filename, bbox_inches='tight')

    # Do not overwrite a result dictionary.  Only add an entry if no result
    # dictionary exists.
    netlist_source = runtime_options['netlist_source']
    results = param['results']
    if isinstance(results, dict):
        results = [results]
    try:
        resultdict = next(
            item for item in results if item['name'] == netlist_source
        )
    except:
        resultdict = {}
    resultdict['status'] = 'done'
    resultdict['name'] = netlist_source
    addnewresult(param, resultdict)

    return canvas
