# airport_finder.py --- A dialog for finding airports
# -*- coding: utf-8 -*-
#
# Copyright (c) 2015  Florent Rougon
#
# This file is distributed under the terms of the DO WHAT THE FUCK YOU WANT TO
# PUBLIC LICENSE version 2, dated December 2004, by Sam Hocevar. You should
# have received a copy of this license along with this file. You can also find
# it at <http://www.wtfpl.net/>.

import tkinter as tk
from tkinter import ttk
from tkinter.messagebox import showinfo, showerror

from ..constants import PROGNAME
from . import widgets
from ..geo import geodesy
from ..misc import normalizeHeading
from . import infowindow
from .tooltip import ToolTip, TreeviewToolTip


def setupTranslationHelper(config):
    global pgettext, ngettext, npgettext
    from .. import misc

    translationHelper = misc.TranslationHelper(config)
    pgettext = translationHelper.pgettext
    ngettext = translationHelper.ngettext
    npgettext = translationHelper.npgettext


def setupEarthMagneticFieldProvider(provider):
    global magField
    magField = provider


class AirportFinder:
    "Airport finder dialog."""

    geodCalc = geodesy.GeodCalc()

    def __init__(self, master, config, app):
        for attr in ("master", "config", "app"):
            setattr(self, attr, locals()[attr])

        setupTranslationHelper(config)

        self.top = tk.Toplevel(self.master)
        self.top.transient(self.master)
        # Uncomment this to disallow interacting with other windows
        # self.top.grab_set()
        self.top.title(_('Airport finder'))
        self.top.protocol("WM_DELETE_WINDOW", self.quit)
        self.top.bind('<Escape>', self.quit)

        tlFrame = ttk.Frame(self.top, padding='12p')
        tlFrame.grid(row=0, column=0, sticky="nsew")
        self.top.grid_rowconfigure(0, weight=100)
        self.top.grid_columnconfigure(0, weight=100)

        # Padding: all or (left, top, right, bottom)
        labelFramesPadding = "15p"

        # *********************************************************************
        # *                   The “Reference airport” frame                   *
        # *********************************************************************
        refAirportFrame = ttk.LabelFrame(tlFrame,
                                         text=_("Reference airport"),
                                         padding=labelFramesPadding)
        refAirportFrame.grid(row=0, column=0, sticky="nsew")
        tlFrame.grid_rowconfigure(0, weight=100)
        tlFrame.grid_columnconfigure(0, weight=100)

        # In the current state, we could spare this frame, which was used to
        # align several things vertically.
        refAirportLeftSubframe = ttk.Frame(refAirportFrame,
                                           padding=(0, 0, "30p", 0))
        refAirportLeftSubframe.grid(row=0, column=0, sticky="nsew")
        refAirportFrame.grid_rowconfigure(0, weight=100)
        refAirportFrame.grid_columnconfigure(0, weight=60)

        refAirportLeftSubSubframe = ttk.Frame(refAirportLeftSubframe)
        refAirportLeftSubSubframe.grid(row=0, column=0, sticky="nsew")
        refAirportLeftSubframe.grid_rowconfigure(0, weight=100)
        refAirportLeftSubframe.grid_columnconfigure(0, weight=100)

        refAirportSearchLabel = ttk.Label(
            refAirportLeftSubSubframe, text=_("Search: "))
        refAirportSearchLabel.grid(row=0, column=0, sticky="w")
        refAirportLeftSubSubframe.grid_rowconfigure(0, weight=100)

        # The link to a StringVar is done in the AirportChooser class
        self.refAirportSearchEntry = ttk.Entry(refAirportLeftSubSubframe)
        self.refAirportSearchEntry.grid(row=0, column=1, sticky="ew")
        refAirportLeftSubSubframe.grid_columnconfigure(1, weight=100)

        # The button binding is done in the AirportChooser class
        self.refAirportSearchClearButton = ttk.Button(
            refAirportLeftSubSubframe, text=_('Clear'))
        self.refAirportSearchClearButton.grid(row=0, column=2, sticky="ew",
                                              padx="12p")
        refAirportLeftSubSubframe.grid_columnconfigure(2, weight=20)

        # The TreeviewSelect event binding is done in the AirportChooser class
        self.refAirportSearchTree = widgets.MyTreeview(
            refAirportFrame, columns=["icao", "name"],
            show="headings", selectmode="browse", height=6)

        self.refAirportSearchTree.grid(row=0, column=1, sticky="nsew")
        refAirportFrame.grid_columnconfigure(1, weight=100)

        def refAirportSearchTreeTooltipFunc(region, itemID, column, self=self):
            if region == "cell":
                icao = self.refAirportSearchTree.set(itemID, "icao")
                found, airport = self.app.readAirportData(icao)

                return airport.tooltipText() if found else None
            else:
                return None

        TreeviewToolTip(self.refAirportSearchTree,
                        refAirportSearchTreeTooltipFunc)

        self.refAirportScrollbar = ttk.Scrollbar(
            refAirportFrame, orient='vertical',
            command=self.refAirportSearchTree.yview, takefocus=0)
        self.refAirportScrollbar.grid(row=0, column=2, sticky="ns")
        self.refAirportSearchTree.config(
            yscrollcommand=self.refAirportScrollbar.set)

        self.refIcao = tk.StringVar()
        self.refIcao.trace("w", self.onRefIcaoWritten)
        self.results = None

        refAirportSearchColumnsList = [
            widgets.Column("icao", _("ICAO"), 0, "w", False, "width",
                           widthText="M"*4),
            widgets.Column("name", _("Name"), 1, "w", True, "width",
                           widthText="M"*30) ]
        refAirportSearchColumns = { col.name: col
                                    for col in refAirportSearchColumnsList }

        # To be able to efficiently gather the following data, we would need to
        # include it in the apt digest file:
        #
        # Column("landRunways", _("Land runways"), 2, "e", False, "width")
        # Column("waterRunways", _("Water runways"), 3, "e", False, "width")
        # Column("helipads", _("Helipads"), 4, "e", False, "width")

        refAirportSearchData = [ (icao, config.airports[icao].name)
                                 for icao in config.sortedIcao() ]

        self.airportChooser = widgets.AirportChooser(
            self.master, self.config, self.refIcao,
            refAirportSearchData, refAirportSearchColumns,
            "icao", # Initially, sort by ICAO
            self.refAirportSearchEntry, self.refAirportSearchClearButton,
            self.refAirportSearchTree)

        self.searchDescrLabelVar = tk.StringVar()

        # Initial “reference airport” selection
        curIcao = config.airport.get()
        tree = self.refAirportSearchTree
        for item in tree.get_children():
            if tree.set(item, "icao") == curIcao:
                # This will set self.refIcao via the TreeviewSelect event
                # handler
                tree.FFGoGotoItemWithIndex(tree.index(item))
                break
        else:
            self.refIcao.set('')

        # *********************************************************************
        # *                         The Search frame                          *
        # *********************************************************************
        searchFrame = ttk.LabelFrame(tlFrame, text=_("Search"),
                                     padding=labelFramesPadding)
        searchFrame.grid(row=1, column=0, sticky="nsew")
        tlFrame.grid_rowconfigure(1, weight=900)

        searchTopFrame = ttk.Frame(searchFrame, padding=(0, 0, 0, "30p"))
        searchTopFrame.grid(row=0, column=0, sticky="nsew")
        searchFrame.grid_columnconfigure(0, weight=100)

        paramsLabel1 = ttk.Label(searchTopFrame,
                                 textvariable=self.searchDescrLabelVar)
        paramsLabel1.grid(row=0, column=0, sticky="w")

        distBoundValidateCmd = self.master.register(self._distBoundValidateFunc)
        distBoundInvalidCmd = self.master.register(self._distBoundInvalidFunc)

        # Minimum distance to the reference airport
        self.minDist = tk.StringVar()
        self.minDist.set('75')
        self.minDistSpinbox = tk.Spinbox(
            searchTopFrame, from_=0, to=10820, increment=1, repeatinterval=20,
            textvariable=self.minDist, width=6, validate="focusout",
            validatecommand=(distBoundValidateCmd, "%P"),
            invalidcommand=(distBoundInvalidCmd, "%W", "%P"))
        self.minDistSpinbox.grid(row=0, column=1)

        paramsLabel2 = ttk.Label(
            searchTopFrame,
            text=pgettext("find airport in range", " ≤ d ≤ "))
        paramsLabel2.grid(row=0, column=2)

        # Maximum distance to the reference airport
        self.maxDist = tk.StringVar()
        self.maxDist.set('100')
        self.maxDistSpinbox = tk.Spinbox(
            searchTopFrame, from_=0, to=10820, increment=1, repeatinterval=20,
            textvariable=self.maxDist, width=6,
            validate="focusout", validatecommand=(distBoundValidateCmd, "%P"),
            invalidcommand=(distBoundInvalidCmd, "%W", "%P"))

        self.maxDistSpinbox.grid(row=0, column=3)

        paramsLabel3 = ttk.Label(searchTopFrame,
                                 text=pgettext("find airport in range",
                                               " nm:"))
        paramsLabel3.grid(row=0, column=4)

        # Number of results
        self.nbResultsTextVar = tk.StringVar()
        nbResultsLabel = ttk.Label(searchTopFrame,
                                   textvariable=self.nbResultsTextVar)
        nbResultsLabel.grid(row=0, column=5, sticky="e")
        searchTopFrame.grid_columnconfigure(5, weight=100)

        searchBottomFrame = ttk.Frame(searchFrame)
        searchBottomFrame.grid(row=1, column=0, sticky="nsew")
        searchFrame.grid_rowconfigure(1, weight=200)

        searchBottomLeftFrame = ttk.Frame(searchBottomFrame)
        searchBottomLeftFrame.grid(row=0, column=0, sticky="nsew")
        searchBottomFrame.grid_rowconfigure(0, weight=100)
        searchBottomFrame.grid_columnconfigure(0, weight=100, pad="30p")

        # Direction (from or to the reference airport)
        searchBottomLeftSubframe1 = ttk.Frame(searchBottomLeftFrame)
        searchBottomLeftSubframe1.grid(row=0, column=0, sticky="nsw")
        searchBottomLeftFrame.grid_rowconfigure(0, weight=100)
        searchBottomLeftFrame.grid_columnconfigure(0, weight=100)

        directionLabel = ttk.Label(searchBottomLeftSubframe1,
                                   text=_("Direction: "))
        directionLabel.grid(row=0, column=0, sticky="w")
        searchBottomLeftSubframe1.grid_columnconfigure(0, weight=100)

        self.directionToRef = tk.IntVar()
        self.directionToRef.set(1)
        self.directionToRef.trace("w", self.displayResults)
        directionToRefButton = ttk.Radiobutton(
            searchBottomLeftSubframe1, variable=self.directionToRef,
            text=_("to reference airport"), value=1,
            padding=("10p", 0, "10p", 0))
        directionToRefButton.grid(row=0, column=1, sticky="w")
        searchBottomLeftSubframe1.grid_rowconfigure(0, pad="5p")
        directionFromRefButton = ttk.Radiobutton(
            searchBottomLeftSubframe1, variable=self.directionToRef,
            text=_("from reference airport"), value=0,
            padding=("10p", 0, "10p", 0))
        directionFromRefButton.grid(row=1, column=1, sticky="w")

        searchBottomLeftSpacerHeight = "20p"
        searchBottomLeftSpacer1 = ttk.Frame(searchBottomLeftFrame)
        searchBottomLeftSpacer1.grid(row=1, column=0, sticky="nsew")
        searchBottomLeftFrame.grid_rowconfigure(
            1, minsize=searchBottomLeftSpacerHeight, weight=100)

        # Magnetic or true bearings
        searchBottomLeftSubframe2 = ttk.Frame(searchBottomLeftFrame)
        searchBottomLeftSubframe2.grid(row=2, column=0, sticky="nsw")
        searchBottomLeftFrame.grid_rowconfigure(2, weight=0)

        bearingsTypeLabel = ttk.Label(searchBottomLeftSubframe2,
                                      text=_("Bearings: "))
        bearingsTypeLabel.grid(row=0, column=0, sticky="w")
        searchBottomLeftSubframe2.grid_columnconfigure(0, weight=100)

        self.bearingsType = tk.StringVar()
        self.bearingsType.trace("w", self.displayResults)
        magBearingsButton = ttk.Radiobutton(
            searchBottomLeftSubframe2, variable=self.bearingsType,
            text=_("magnetic"), value="magnetic", padding=("10p", 0, "10p", 0))
        magBearingsButton.grid(row=0, column=1, sticky="w")
        searchBottomLeftSubframe2.grid_rowconfigure(0, pad="5p")
        trueBearingsButton = ttk.Radiobutton(
            searchBottomLeftSubframe2, variable=self.bearingsType,
            text=_("true"), value="true", padding=("10p", 0, "10p", 0))
        trueBearingsButton.grid(row=1, column=1, sticky="w")

        if magField is not None:
            self.bearingsType.set("magnetic")
        else:
            self.bearingsType.set("true")
            magBearingsButton.state(["disabled"])

        searchBottomLeftSpacer2 = ttk.Frame(searchBottomLeftFrame)
        searchBottomLeftSpacer2.grid(row=3, column=0, sticky="nsew")
        searchBottomLeftFrame.grid_rowconfigure(
            3, minsize=searchBottomLeftSpacerHeight, weight=100)

        # Length unit (nautical miles or kilometers)
        searchBottomLeftSubframe3 = ttk.Frame(searchBottomLeftFrame)
        searchBottomLeftSubframe3.grid(row=4, column=0, sticky="nsw")
        searchBottomLeftFrame.grid_rowconfigure(4, weight=0)

        lengthUnitLabel = ttk.Label(searchBottomLeftSubframe3,
                                    text=_("Distances in: "))
        lengthUnitLabel.grid(row=0, column=0, sticky="w")
        searchBottomLeftSubframe3.grid_columnconfigure(0, weight=100)

        self.lengthUnit = tk.StringVar()
        self.lengthUnit.set("nautical mile")
        self.lengthUnit.trace("w", self.displayResults)
        nautMilesButton = ttk.Radiobutton(
            searchBottomLeftSubframe3, variable=self.lengthUnit,
            text=_("nautical miles"), value="nautical mile",
            padding=("10p", 0, "10p", 0))
        nautMilesButton.grid(row=0, column=1, sticky="w")
        searchBottomLeftSubframe3.grid_rowconfigure(0, pad="5p")
        kilometersButton = ttk.Radiobutton(
            searchBottomLeftSubframe3, variable=self.lengthUnit,
            text=_("kilometers"), value="kilometer",
            padding=("10p", 0, "10p", 0))
        kilometersButton.grid(row=1, column=1, sticky="w")

        searchBottomLeftSpacer3 = ttk.Frame(searchBottomLeftFrame)
        searchBottomLeftSpacer3.grid(row=5, column=0, sticky="nsew")
        searchBottomLeftFrame.grid_rowconfigure(
            5, minsize=searchBottomLeftSpacerHeight, weight=100)

        # Calculation method (Vincenty or Karney)
        searchBottomLeftSubframe4 = ttk.Frame(searchBottomLeftFrame)
        searchBottomLeftSubframe4.grid(row=6, column=0, sticky="nsw")
        searchBottomLeftFrame.grid_rowconfigure(6, weight=0)

        calcMethodLabel = ttk.Label(searchBottomLeftSubframe4,
                                    text=_("Calculation method: "))
        calcMethodLabel.grid(row=0, column=0, sticky="w")
        searchBottomLeftSubframe4.grid_columnconfigure(0, weight=100)

        self.calcMethodVar = tk.StringVar()
        # Vincenty's method is much faster than Karney's one, and since the
        # calculation over about 34000 airports takes some time, let's pick the
        # fastest one as default even if it may fail for a few rare pairs of
        # airports (which will be signaled, so the user can select the Karney
        # method for these specific cases and have all results in the end).
        self.calcMethodVar.set("vincentyInverseWithFallback")
        karneyMethodRadioButton = ttk.Radiobutton(
            searchBottomLeftSubframe4, variable=self.calcMethodVar,
            text=_("Karney"), value="karneyInverse",
            padding=("10p", 0, "10p", 0))
        karneyMethodRadioButton.grid(row=0, column=1, sticky="w")
        searchBottomLeftSubframe4.grid_rowconfigure(0, pad="5p")
        vincentyMethodRadioButton = ttk.Radiobutton(
            searchBottomLeftSubframe4, variable=self.calcMethodVar,
            text=_("Vincenty et al."), value="vincentyInverseWithFallback",
            padding=("10p", 0, "10p", 0))
        vincentyMethodRadioButton.grid(row=1, column=1, sticky="w")

        # Tooltip for the calculation method
        if self.geodCalc.karneyMethodAvailable():
            calcMethodHint = ""
        else:
            karneyMethodRadioButton.state(["disabled"])
            calcMethodHint = (" "
                "In order to be able to use it here, you need to have "
                "installed GeographicLib's implementation for the Python "
                "installation you are using to run {prg}.").format(prg=PROGNAME)

        calcMethodTooltipText = _(
            "Vincenty's method is faster than Karney's one, but there are "
            "some particular cases in which the algorithm can't do the "
            "computation. Karney's method should handle all possible "
            "cases.{complement}\n\n"
            "Note: changing this option won't have any effect until the search "
            "is restarted.").format(complement=calcMethodHint)
        ToolTip(calcMethodLabel, calcMethodTooltipText, autowrap=True)

        searchBottomLeftSpacer4 = ttk.Frame(searchBottomLeftFrame)
        searchBottomLeftSpacer4.grid(row=7, column=0, sticky="nsew")
        searchBottomLeftFrame.grid_rowconfigure(
            7, minsize=searchBottomLeftSpacerHeight, weight=100)

        # Push buttons ('Search' and 'Choose selected airport')
        searchBottomLeftSubframe5 = ttk.Frame(searchBottomLeftFrame)
        searchBottomLeftSubframe5.grid(row=8, column=0, sticky="nsew")
        searchBottomLeftFrame.grid_rowconfigure(8, weight=0)

        self.searchButton = ttk.Button(
            searchBottomLeftSubframe5, text=_('Search'),
            command=self.search, padding="10p")
        self.searchButton.grid(row=0, column=0)
        searchBottomLeftSubframe5.grid_rowconfigure(0, weight=100)
        searchBottomLeftSubframe5.grid_columnconfigure(0, weight=100)

        # Alt-s keyboard shortcut for the 'Search' button
        self.top.bind('<Alt-KeyPress-s>',
                      lambda event, self=self: self.searchButton.invoke())
        ToolTip(self.searchButton,
                _("Find all airports matching the specified criteria.\n"
                  "Can be run with Alt-S."),
                autowrap=True)

        self.chooseSelectedAptButton = ttk.Button(
            searchBottomLeftSubframe5, text=_('Choose selected airport'),
            command=self.chooseSelectedAirport, padding="4p")
        self.chooseSelectedAptButton.grid(row=0, column=1)
        searchBottomLeftSubframe5.grid_columnconfigure(1, weight=100)

        self.chooseSelectedAptButton.state(["disabled"])
        ToolTip(self.chooseSelectedAptButton,
                _("Choose the selected airport and close this dialog"),
                autowrap=True)

        # Treeview widget used to display the search results
        resultsColumnsList = [
            widgets.Column("icao", _("ICAO"), 0, "w", False, "width",
                           widthText="M"*4),
            widgets.Column("name", _("Name"), 1, "w", True, "width",
                           widthText="M"*25),
            # The distance 'formatFunc' will be set later (depends on the
            # chosen unit).
            widgets.Column("distance", _("Distance"), 2, "e", False, "width",
                           widthText="M"*6),
            widgets.Column("initBearing", _("Init. bearing"), 3, "e",
                           False, "width", widthText="M"*4, formatFunc=str),
            widgets.Column("finalBearing", _("Final bearing"), 4, "e",
                           False, "width", widthText="M"*4, formatFunc=str) ]
        self.resultsColumns = { col.name: col for col in resultsColumnsList }
        resCols = [ col.name for col in resultsColumnsList ]

        self.resultsTree = widgets.MyTreeview(
            searchBottomFrame, columns=resCols, show="headings",
            selectmode="browse", height=10)

        self.resultsTree.grid(row=0, column=1, sticky="nsew")
        searchBottomFrame.grid_columnconfigure(1, weight=300)

        def resultsTreeTooltipFunc(region, itemID, column, self=self):
            if region == "cell":
                icao = self.resultsTree.set(itemID, "icao")
                found, airport = self.app.readAirportData(icao)

                return airport.tooltipText() if found else None
            else:
                return None

        TreeviewToolTip(self.resultsTree, resultsTreeTooltipFunc)

        self.resultsScrollbar = ttk.Scrollbar(
            searchBottomFrame, orient='vertical',
            command=self.resultsTree.yview, takefocus=0)
        self.resultsScrollbar.grid(row=0, column=2, sticky="ns")
        self.resultsTree.config(yscrollcommand=self.resultsScrollbar.set)

        # This will hold the ICAO for the airport selected in the results tree.
        self.selectedIcao = tk.StringVar()
        # Logic around the Treeview widget used to display the results
        self.resultsManager = TabularDataManager(
            self.master, self.config, self.selectedIcao, [], self.resultsColumns,
                 "icao", "distance", self.resultsTree)

    def _distBoundValidateFunc(self, text):
        """Validate a string that should contain a distance measure."""
        try:
            f = float(text)
        except ValueError:
            return False

        return (f >= 0.0)

    def _distBoundInvalidFunc(self, widgetPath, text):
        """Callback function used when an invalid distance has been input."""
        widget = self.master.nametowidget(widgetPath)

        if widget is self.minDistSpinbox:
            message = _('Invalid minimum distance value')
        elif widget is self.maxDistSpinbox:
            message = _('Invalid maximum distance value')
        else:
            assert False, "Unexpected widget: " + repr(widget)

        detail = _("'{input}' is not a valid distance. Only non-negative "
                   "decimal numbers are allowed here.").format(input=text)
        showerror(_('{prg}').format(prg=PROGNAME), message, detail=detail,
                  parent=self.top)

        widget.focus_set()

    def quit(self, event=None):
        """Destroy the Airport Finder dialog."""
        self.top.destroy()

    # Accept any arguments to allow safe use as a Tkinter variable observer
    def onRefIcaoWritten(self, *args):
        icao = self.refIcao.get()
        self.results = None     # the results were for the previous ref airport

        self.searchDescrLabelVar.set(
            _("Find airports at distance d from {refIcao} where ").format(
            refIcao=icao))

    def search(self):
        """Main method of the Airport Finder dialog."""
        # Validate the contents of these spinboxes in case one of them still
        # has the focus (which is possible if this method was invoked by a
        # keyboard shortcut).
        for varname, widget in (("minDist", self.minDistSpinbox),
                                ("maxDist", self.maxDistSpinbox)):
            val = getattr(self, varname).get()
            if not self._distBoundValidateFunc(val):
                self._distBoundInvalidFunc(str(widget), val)
                return None

        self.searchButton.state(["disabled"])
        self.chooseSelectedAptButton.state(["disabled"])
        message = _("Calculating distances and bearings...")
        infoWindow = infowindow.InfoWindow(self.master, text=message)

        try:
            res = self._search()
        finally:
            infoWindow.destroy()
            self.searchButton.state(["!disabled"])

        if res is not None:
            if res:             # number of omitted results
                message = _('Some results might be missing')
                detail = _(
                    "Could not compute distance and bearings between "
                    "{refICAO} and the following airport(s): {aptList}.\n\n"
                    "Vincenty's algorithm for the geodetic inverse problem "
                    "is known not to handle all possible cases. Use Karney's "
                    "calculation method if you want to see all results.\n\n"
                    "Normally, this problem can only happen between airports "
                    "that are antipodal or nearly so. Therefore, if you are "
                    "not interested in such cases, you can probably ignore "
                    "this message.").format(refICAO=self.refIcao.get(),
                            aptList=', '.join(sorted(res)))

                showinfo(_('{prg}').format(prg=PROGNAME), message,
                         detail=detail, parent=self.top)

            self.displayResults()
            if self.results:
                self.chooseSelectedAptButton.state(["!disabled"])


    def _search(self):
        refIcao = self.refIcao.get()

        # Convert from nautical miles to meters (the contents of these
        # variables has been validated in search()).
        minDist = 1852*float(self.minDist.get())
        maxDist = 1852*float(self.maxDist.get())
        self.results = []
        omittedResults = set()

        if refIcao:
            refApt = self.config.airports[refIcao]
            refAptLat, refAptLon = refApt.lat, refApt.lon # for performance

            distCalcFunc = getattr(self.geodCalc, self.calcMethodVar.get())
            airportsDict = self.config.airports

            for airport in airportsDict.values():
                try:
                    g = distCalcFunc(airport.lat, airport.lon,
                                     refAptLat, refAptLon)
                except geodesy.VincentyInverseError:
                    omittedResults.add(airport.icao)
                    continue

                if minDist <= g["s12"] <= maxDist:
                    self.results.append(
                        (airport, g["s12"], g["azi1"], g["azi2"]))

            return omittedResults
        else:
            return None

    # Accept any arguments to allow safe use as a Tkinter variable observer
    def displayResults(self, *args):
        """Display the last search results."""
        if self.results is None or not self.refIcao.get():
            return

        l = []

        magBearings = (self.bearingsType.get() == "magnetic")
        if magBearings:
            # This is correct, because self.results is set to None whenever
            # self.refIcao is changed.
            refApt = self.config.airports[self.refIcao.get()]
            refAptLat, refAptLon = refApt.lat, refApt.lon
            magDeclAtRef = magField.decl(refAptLat, refAptLon)

            latLon = [ (airport.lat, airport.lon)
                       for airport, *rest in self.results ]
            magDecl = magField.batchDecl(latLon)

        if self.lengthUnit.get() == "nautical mile":
            self.resultsColumns["distance"].formatFunc = (
                lambda d: str(round(d / 1852))) # exact conversion
        elif self.lengthUnit.get() == "kilometer":
            self.resultsColumns["distance"].formatFunc = (
                lambda d: str(round(d / 1000)))
        else:
            assert False, "Unexpected length unit: {!r}".format(
                self.lengthUnit.get())

        directionToRef = self.directionToRef.get()

        for i, (airport, distance, azi1, azi2) in enumerate(self.results):
            if directionToRef:
                if magBearings:
                    initBearing = normalizeHeading(azi1 - magDecl[i])
                    finalBearing = normalizeHeading(azi2 - magDeclAtRef)
                else:
                    initBearing = normalizeHeading(azi1)
                    finalBearing = normalizeHeading(azi2)
            else:
                if magBearings:
                    initBearing = normalizeHeading(azi2 + 180.0 - magDeclAtRef)
                    finalBearing = normalizeHeading(azi1 + 180.0 - magDecl[i])
                else:
                    initBearing = normalizeHeading(azi2 + 180.0)
                    finalBearing = normalizeHeading(azi1 + 180.0)

            l.append([airport.icao, airport.name, distance, initBearing,
                      finalBearing])

        self.resultsManager.loadData(l)
        nbRes = len(self.results)
        self.nbResultsTextVar.set(
            ngettext("Found {} airport", "Found {} airports", nbRes)
            .format(nbRes))

    def chooseSelectedAirport(self):
        """
        Choose the results-selected airport and close the Airport Finder dialog."""
        self.app.selectNewAirport(self.selectedIcao.get())
        self.quit()


class TabularDataManager:
    """Class interfacing Ttk's Treeview widget with a basic data model.

    Similar, but not identical to widgets.AirportChooser.

    """
    def __init__(self, master, config, identVar, treeData, columnsMetadata,
                 identColName, initSortBy, treeWidget):
        """Constructor for AirportChooser instances.

        master          -- Tk master object (“root”)
        config          -- Config instance
        identVar        -- StringVar instance that will be automatically
                           updated to reflect the currently selected
                           item (currently selected in the Treeview
                           widget)
        treeData        -- sequence of tuples where each tuple has one
                           element per column displayed in the Treeview.
                           This is the complete data set used to fill
                           the Treeview. The word “tuple” is used to
                           ease understanding here, but any sequence
                           can do.
        columnsMetadata -- mapping from symbolic column names for the
                           Ttk Treeview widget to widgets.Column
                           instances
        identColName    -- symbolic name of the column whose contents is
                           linked to 'identVar'; the data held for this
                           column in treeData must be of type 'str' in
                           order to be compatible with 'identVar'.
        initSortBy      -- symbolic name of the column used to initially
                           sort the Treeview widget
        treeWidget      -- Ttk Treeview widget used as a multicolumn
                           list (in other words, a table)

        The 'identVar' StringVar instance and the Treeview widget must
        be created by the caller. However, this constructor takes care
        of connecting them with the appropriate methods.

        """
        _attrs = ("master", "config", "identVar", "treeData", "columnsMetadata",
                  "identColName", "treeWidget")
        for attr in _attrs:
            setattr(self, attr, locals()[attr])

        self.sortBy = initSortBy

        # List of item indices (into treeData) that are the result of the last
        # sort operation (i.e., this describes a permutation on treeData).
        self.indices = []

        columnMapping = {}
        for col in self.columnsMetadata.values():
            self.configColumn(col)
            columnMapping[col.dataIndex] = col

        # Column instances in the order of their dataIndex
        self.columns = [ columnMapping[i]
                         for i in sorted(columnMapping.keys()) ]
        for i, col in enumerate(self.columns):
            assert i == col.dataIndex, (i, col.dataIndex)

        self.treeWidget.bind('<<TreeviewSelect>>', self.onTreeviewSelect)
        self.updateContents()

    def loadData(self, treeData):
        """Load a new dataset into the Treeview widget."""
        self.treeData = treeData
        self.updateContents()

    def updateContents(self, dataChanged=True):
        """Fill the Treeview widget based on self.treeData and sorting params.

        If one is sure that neither the items in self.treeData nor the
        column formatting functions have changed since the Treeview was
        last updated, differences in the Treeview display can only come
        from the order in which items are sorted. In such a case, one
        may call this method with 'dataChanged=False' in order to save
        time in the case where nothing has changed (i.e., after sorting,
        the items would be in the same order as saved in self.indices).

        """
        col = self.columnsMetadata[self.sortBy]
        treeData = self.treeData  # for performance
        dataIndex = col.dataIndex # ditto

        l = [ (treeData[i][dataIndex], i) for i in range(len(treeData)) ]
        if col.sortFunc is not None:
            keyFunc = lambda t: col.sortFunc(t[0])
        else:
            keyFunc = lambda t: t[0]

        l.sort(key=keyFunc, reverse=int(col.sortOrder))
        # Describes the permutation on treeData giving the desired sort order
        indices = [ t[1] for t in l ]

        if self.indices != indices or dataChanged:
            self.indices = indices
            self._updateTreeWidget()

    def _updateTreeWidget(self):
        """Update the contents of the Treeview widget."""
        curIdent = self.identVar.get()
        identColName = self.identColName
        tree = self.treeWidget
        # Delete all children of the root element. Even when the elements just
        # need to be put in a different order, it is much faster this way than
        # using tree.move() for each element.
        tree.delete(*tree.get_children())

        hasSpecialFormatter = any(
            ( col.formatFunc is not None for col in self.columns ))

        if hasSpecialFormatter:
            columns = self.columns

            formatter = []
            identity = lambda x: x
            for dataIndex in range(len(self.columns)):
                f = columns[dataIndex].formatFunc
                formatter.append(identity if f is None else f)

            for idx in self.indices:
                rawValues = self.treeData[idx]
                values = [ formatter[dataIndex](rawValue)
                           for dataIndex, rawValue in enumerate(rawValues) ]
                tree.insert("", "end", values=values)
        else:
            # Optimize the case where no column has a formatter function
            for idx in self.indices:
                tree.insert("", "end", values=self.treeData[idx])

        # Select a suitable item in the repopulated tree, if it is non-empty.
        if self.indices:
            for item in tree.get_children():
                if tree.set(item, identColName) == curIdent:
                    # This will set self.identVar via the TreeviewSelect
                    # event handler.
                    tree.FFGoGotoItemWithIndex(tree.index(item))
                    break
            else:
                # We could not find the previously-selected airport
                # → select the first one in the tree.
                tree.FFGoGotoItemWithIndex(0)
        else:                   # empty tree, we can't select anything
            self.identVar.set('')

    def configColumn(self, col):
        measure = self.config.treeviewHeadingFont.measure
        if col.widthText is not None:
            width = max(map(measure, (col.widthText + "  ", col.title + "  ")))
        else:
            width = measure(col.title + "  ")

        kwargs = col.columnKwargs.copy()
        kwargs[col.widthKeyword] = width

        self.treeWidget.column(
            col.name, anchor=col.anchor, stretch=col.stretch, **kwargs)

        def sortFunc(col=col):
            self.sortTree(col)
        self.treeWidget.heading(col.name, text=col.title, command=sortFunc)

    def sortTree(self, col):
        """Sort tree contents when a column header is clicked on."""
        if self.sortBy == col.name:
            col.sortOrder = col.sortOrder.reverse()
        else:
            self.sortBy = col.name
            col.sortOrder = widgets.SortOrder.ascending

        self.updateContents(dataChanged=False) # repopulate the Treeview

    def onTreeviewSelect(self, event=None):
        tree = self.treeWidget

        currentSel = tree.selection()
        assert currentSel, "Unexpected empty selection in TreeviewSelect event"

        self.identVar.set(tree.set(currentSel[0], self.identColName))