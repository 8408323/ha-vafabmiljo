//#region \0rolldown/runtime.js
var e = (e, t) => () => (t || (e((t = { exports: {} }).exports, t), e = null), t.exports), t = /* @__PURE__ */ e(((e) => {
	var t = Symbol.for("react.transitional.element"), n = Symbol.for("react.portal"), r = Symbol.for("react.fragment"), i = Symbol.for("react.strict_mode"), a = Symbol.for("react.profiler"), o = Symbol.for("react.consumer"), s = Symbol.for("react.context"), c = Symbol.for("react.forward_ref"), l = Symbol.for("react.suspense"), u = Symbol.for("react.memo"), d = Symbol.for("react.lazy"), f = Symbol.for("react.activity"), p = Symbol.for("react.view_transition"), m = Symbol.iterator;
	function h(e) {
		return typeof e != "object" || !e ? null : (e = m && e[m] || e["@@iterator"], typeof e == "function" ? e : null);
	}
	var g = {
		isMounted: function() {
			return !1;
		},
		enqueueForceUpdate: function() {},
		enqueueReplaceState: function() {},
		enqueueSetState: function() {}
	}, _ = Object.assign, v = {};
	function y(e, t, n) {
		this.props = e, this.context = t, this.refs = v, this.updater = n || g;
	}
	y.prototype.isReactComponent = {}, y.prototype.setState = function(e, t) {
		if (typeof e != "object" && typeof e != "function" && e != null) throw Error("takes an object of state variables to update or a function which returns an object of state variables.");
		this.updater.enqueueSetState(this, e, t, "setState");
	}, y.prototype.forceUpdate = function(e) {
		this.updater.enqueueForceUpdate(this, e, "forceUpdate");
	};
	function b() {}
	b.prototype = y.prototype;
	function x(e, t, n) {
		this.props = e, this.context = t, this.refs = v, this.updater = n || g;
	}
	var S = x.prototype = new b();
	S.constructor = x, _(S, y.prototype), S.isPureReactComponent = !0;
	var C = Array.isArray;
	function w() {}
	var T = {
		H: null,
		A: null,
		T: null,
		S: null
	}, E = Object.prototype.hasOwnProperty;
	function D(e, n, r) {
		var i = r.ref;
		return {
			$$typeof: t,
			type: e,
			key: n,
			ref: i === void 0 ? null : i,
			props: r
		};
	}
	function O(e, t) {
		return D(e.type, t, e.props);
	}
	function k(e) {
		return typeof e == "object" && !!e && e.$$typeof === t;
	}
	function A(e) {
		var t = {
			"=": "=0",
			":": "=2"
		};
		return "$" + e.replace(/[=:]/g, function(e) {
			return t[e];
		});
	}
	var j = /\/+/g;
	function M(e, t) {
		return typeof e == "object" && e && e.key != null ? A("" + e.key) : t.toString(36);
	}
	function N(e) {
		switch (e.status) {
			case "fulfilled": return e.value;
			case "rejected": throw e.reason;
			default: switch (typeof e.status == "string" ? e.then(w, w) : (e.status = "pending", e.then(function(t) {
				e.status === "pending" && (e.status = "fulfilled", e.value = t);
			}, function(t) {
				e.status === "pending" && (e.status = "rejected", e.reason = t);
			})), e.status) {
				case "fulfilled": return e.value;
				case "rejected": throw e.reason;
			}
		}
		throw e;
	}
	function P(e, r, i, a, o) {
		var s = typeof e;
		(s === "undefined" || s === "boolean") && (e = null);
		var c = !1;
		if (e === null) c = !0;
		else switch (s) {
			case "bigint":
			case "string":
			case "number":
				c = !0;
				break;
			case "object": switch (e.$$typeof) {
				case t:
				case n:
					c = !0;
					break;
				case d: return c = e._init, P(c(e._payload), r, i, a, o);
			}
		}
		if (c) return o = o(e), c = a === "" ? "." + M(e, 0) : a, C(o) ? (i = "", c != null && (i = c.replace(j, "$&/") + "/"), P(o, r, i, "", function(e) {
			return e;
		})) : o != null && (k(o) && (o = O(o, i + (o.key == null || e && e.key === o.key ? "" : ("" + o.key).replace(j, "$&/") + "/") + c)), r.push(o)), 1;
		c = 0;
		var l = a === "" ? "." : a + ":";
		if (C(e)) for (var u = 0; u < e.length; u++) a = e[u], s = l + M(a, u), c += P(a, r, i, s, o);
		else if (u = h(e), typeof u == "function") for (e = u.call(e), u = 0; !(a = e.next()).done;) a = a.value, s = l + M(a, u++), c += P(a, r, i, s, o);
		else if (s === "object") {
			if (typeof e.then == "function") return P(N(e), r, i, a, o);
			throw r = String(e), Error("Objects are not valid as a React child (found: " + (r === "[object Object]" ? "object with keys {" + Object.keys(e).join(", ") + "}" : r) + "). If you meant to render a collection of children, use an array instead.");
		}
		return c;
	}
	function F(e, t, n) {
		if (e == null) return e;
		var r = [], i = 0;
		return P(e, r, "", "", function(e) {
			return t.call(n, e, i++);
		}), r;
	}
	function I(e) {
		if (e._status === -1) {
			var t = e._result, n = t();
			n.then(function(t) {
				(e._status === 0 || e._status === -1) && (e._status = 1, e._result = t, n.status === void 0 && (n.status = "fulfilled", n.value = t));
			}, function(t) {
				(e._status === 0 || e._status === -1) && (e._status = 2, e._result = t, n.status === void 0 && (n.status = "rejected", n.reason = t));
			}), e._status === -1 && (e._status = 0, e._result = n);
		}
		if (e._status === 1) return e._result.default;
		throw e._result;
	}
	var L = typeof reportError == "function" ? reportError : function(e) {
		if (typeof window == "object" && typeof window.ErrorEvent == "function") {
			var t = new window.ErrorEvent("error", {
				bubbles: !0,
				cancelable: !0,
				message: typeof e == "object" && e && typeof e.message == "string" ? String(e.message) : String(e),
				error: e
			});
			if (!window.dispatchEvent(t)) return;
		} else if (typeof process == "object" && typeof process.emit == "function") {
			process.emit("uncaughtException", e);
			return;
		}
		console.error(e);
	};
	function R(e) {
		var t = T.T, n = {};
		n.types = t === null ? null : t.types, T.T = n;
		try {
			var r = e(), i = T.S;
			i !== null && i(n, r), typeof r == "object" && r && typeof r.then == "function" && r.then(w, L);
		} catch (e) {
			L(e);
		} finally {
			t !== null && n.types !== null && (t.types = n.types), T.T = t;
		}
	}
	function z(e) {
		var t = T.T;
		if (t !== null) {
			var n = t.types;
			n === null ? t.types = [e] : n.indexOf(e) === -1 && n.push(e);
		} else R(z.bind(null, e));
	}
	var B = {
		map: F,
		forEach: function(e, t, n) {
			F(e, function() {
				t.apply(this, arguments);
			}, n);
		},
		count: function(e) {
			var t = 0;
			return F(e, function() {
				t++;
			}), t;
		},
		toArray: function(e) {
			return F(e, function(e) {
				return e;
			}) || [];
		},
		only: function(e) {
			if (!k(e)) throw Error("React.Children.only expected to receive a single React element child.");
			return e;
		}
	};
	e.Activity = f, e.Children = B, e.Component = y, e.Fragment = r, e.Profiler = a, e.PureComponent = x, e.StrictMode = i, e.Suspense = l, e.ViewTransition = p, e.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE = T, e.__COMPILER_RUNTIME = {
		__proto__: null,
		c: function(e) {
			return T.H.useMemoCache(e);
		}
	}, e.addTransitionType = z, e.cache = function(e) {
		return function() {
			return e.apply(null, arguments);
		};
	}, e.cacheSignal = function() {
		return null;
	}, e.cloneElement = function(e, t, n) {
		if (e == null) throw Error("The argument must be a React element, but you passed " + e + ".");
		var r = _({}, e.props), i = e.key;
		if (t != null) for (a in t.key !== void 0 && (i = "" + t.key), t) !E.call(t, a) || a === "key" || a === "__self" || a === "__source" || a === "ref" && t.ref === void 0 || (r[a] = t[a]);
		var a = arguments.length - 2;
		if (a === 1) r.children = n;
		else if (1 < a) {
			for (var o = Array(a), s = 0; s < a; s++) o[s] = arguments[s + 2];
			r.children = o;
		}
		return D(e.type, i, r);
	}, e.createContext = function(e) {
		return e = {
			$$typeof: s,
			_currentValue: e,
			_currentValue2: e,
			_threadCount: 0,
			Provider: null,
			Consumer: null
		}, e.Provider = e, e.Consumer = {
			$$typeof: o,
			_context: e
		}, e;
	}, e.createElement = function(e, t, n) {
		var r, i = {}, a = null;
		if (t != null) for (r in t.key !== void 0 && (a = "" + t.key), t) E.call(t, r) && r !== "key" && r !== "__self" && r !== "__source" && (i[r] = t[r]);
		var o = arguments.length - 2;
		if (o === 1) i.children = n;
		else if (1 < o) {
			for (var s = Array(o), c = 0; c < o; c++) s[c] = arguments[c + 2];
			i.children = s;
		}
		if (e && e.defaultProps) for (r in o = e.defaultProps, o) i[r] === void 0 && (i[r] = o[r]);
		return D(e, a, i);
	}, e.createRef = function() {
		return { current: null };
	}, e.forwardRef = function(e) {
		return {
			$$typeof: c,
			render: e
		};
	}, e.isValidElement = k, e.lazy = function(e) {
		return {
			$$typeof: d,
			_payload: {
				_status: -1,
				_result: e
			},
			_init: I
		};
	}, e.memo = function(e, t) {
		return {
			$$typeof: u,
			type: e,
			compare: t === void 0 ? null : t
		};
	}, e.startTransition = R, e.unstable_useCacheRefresh = function() {
		return T.H.useCacheRefresh();
	}, e.use = function(e) {
		return T.H.use(e);
	}, e.useActionState = function(e, t, n) {
		return T.H.useActionState(e, t, n);
	}, e.useCallback = function(e, t) {
		return T.H.useCallback(e, t);
	}, e.useContext = function(e) {
		return T.H.useContext(e);
	}, e.useDebugValue = function() {}, e.useDeferredValue = function(e, t) {
		return T.H.useDeferredValue(e, t);
	}, e.useEffect = function(e, t) {
		return T.H.useEffect(e, t);
	}, e.useEffectEvent = function(e) {
		return T.H.useEffectEvent(e);
	}, e.useId = function() {
		return T.H.useId();
	}, e.useImperativeHandle = function(e, t, n) {
		return T.H.useImperativeHandle(e, t, n);
	}, e.useInsertionEffect = function(e, t) {
		return T.H.useInsertionEffect(e, t);
	}, e.useLayoutEffect = function(e, t) {
		return T.H.useLayoutEffect(e, t);
	}, e.useMemo = function(e, t) {
		return T.H.useMemo(e, t);
	}, e.useOptimistic = function(e, t) {
		return T.H.useOptimistic(e, t);
	}, e.useReducer = function(e, t, n) {
		return T.H.useReducer(e, t, n);
	}, e.useRef = function(e) {
		return T.H.useRef(e);
	}, e.useState = function(e) {
		return T.H.useState(e);
	}, e.useSyncExternalStore = function(e, t, n) {
		return T.H.useSyncExternalStore(e, t, n);
	}, e.useTransition = function() {
		return T.H.useTransition();
	}, e.version = "19.3.0";
})), n = /* @__PURE__ */ e(((e, n) => {
	n.exports = t();
})), r = /* @__PURE__ */ e(((e) => {
	var t = Symbol.for("react.transitional.element"), n = Symbol.for("react.fragment");
	function r(e, n, r) {
		var i = null;
		if (r !== void 0 && (i = "" + r), n.key !== void 0 && (i = "" + n.key), "key" in n) for (var a in r = {}, n) a !== "key" && (r[a] = n[a]);
		else r = n;
		return n = r.ref, {
			$$typeof: t,
			type: e,
			key: i,
			ref: n === void 0 ? null : n,
			props: r
		};
	}
	e.Fragment = n, e.jsx = r, e.jsxs = r;
})), i = /* @__PURE__ */ e(((e, t) => {
	t.exports = r();
})), a = i(), o = 35, s = 385, c = 112, l = ([e, t, n]) => [s + (e - t) * .866 * o, c + (e + t) * .5 * o - n * o], u = (e) => e.map((e) => l(e).join(",")).join(" "), d = [
	{
		re: /papp|plast|förpack|tidning/i,
		body: "#24272c",
		lid: "#30343b",
		w: .86,
		d: .87,
		h: 1.1,
		split: !0
	},
	{
		re: /mat|bio|kompost/i,
		body: "#6b4226",
		lid: "#7a4e30",
		w: .48,
		d: .555,
		h: 1.065
	},
	{
		re: /rest|hush/i,
		body: "#7fa66a",
		lid: "#9cc08a",
		w: .48,
		d: .73,
		h: 1.07
	}
], f = {
	re: /./,
	body: "#4a5260",
	lid: "#5d6675",
	w: .58,
	d: .73,
	h: 1.07
}, p = (e) => d.find((t) => t.re.test(e)) ?? f, m = (e) => {
	let t = p(e);
	return t === d[0] ? "#8e44ad" : t.lid;
}, h = 1.3;
function g(e, t, n, r, i, o, s, c, l) {
	return /* @__PURE__ */ (0, a.jsxs)("g", { children: [
		/* @__PURE__ */ (0, a.jsx)("polygon", {
			points: u([
				[
					t,
					n,
					i
				],
				[
					t,
					r,
					i
				],
				[
					t,
					r,
					o
				],
				[
					t,
					n,
					o
				]
			]),
			fill: c
		}),
		/* @__PURE__ */ (0, a.jsx)("polygon", {
			points: u([
				[
					e,
					r,
					i
				],
				[
					t,
					r,
					i
				],
				[
					t,
					r,
					o
				],
				[
					e,
					r,
					o
				]
			]),
			fill: s
		}),
		/* @__PURE__ */ (0, a.jsx)("polygon", {
			points: u([
				[
					e,
					n,
					o
				],
				[
					t,
					n,
					o
				],
				[
					t,
					r,
					o
				],
				[
					e,
					r,
					o
				]
			]),
			fill: l
		})
	] });
}
var _ = (e, t) => "#" + [
	1,
	3,
	5
].map((n) => Math.round(Math.min(255, parseInt(e.slice(n, n + 2), 16) * t)).toString(16).padStart(2, "0")).join("");
function v({ x: e, y: t, type: n, glow: r }) {
	let i = p(n), o = i.w * h, s = i.d * h, c = i.h * h, [d, f] = l([
		e + o / 2,
		t + s / 2,
		0
	]), m = (e, n, r, i, o) => /* @__PURE__ */ (0, a.jsx)("polygon", {
		points: u([
			[
				e,
				t + s + .01,
				r
			],
			[
				n,
				t + s + .01,
				r
			],
			[
				n,
				t + s + .01,
				i
			],
			[
				e,
				t + s + .01,
				i
			]
		]),
		fill: o
	}), v = (e, t, n, r, i, o) => /* @__PURE__ */ (0, a.jsx)("polygon", {
		points: u([
			[
				e,
				n,
				i
			],
			[
				t,
				n,
				i
			],
			[
				t,
				r,
				i
			],
			[
				e,
				r,
				i
			]
		]),
		fill: o
	});
	return /* @__PURE__ */ (0, a.jsxs)("g", { children: [
		r && /* @__PURE__ */ (0, a.jsx)("ellipse", {
			cx: d,
			cy: f,
			rx: 22 + 22 * o,
			ry: 12 + 12 * o,
			className: "bin-glow"
		}),
		g(e, e + o, t, t + s, 0, c, i.body, _(i.body, .78), _(i.body, 1.15)),
		g(e - .04, e + o + .04, t - .04, t + s + .06, c, c + .1, i.lid, _(i.lid, .78), _(i.lid, 1.18)),
		g(e + .08, e + o - .08, t - .12, t - .04, c + .05, c + .16, _(i.lid, .7), _(i.lid, .6), _(i.lid, .9)),
		m(e + .12, e + o - .12, c - .18, c - .08, _(i.body, .6)),
		i.split ? /* @__PURE__ */ (0, a.jsxs)(a.Fragment, { children: [
			v(e + o / 2 - .05, e + o / 2 + .05, t - .04, t + s + .06, c + .14, "#15171a"),
			v(e + .1, e + .28, t + s - .38, t + s - .14, c + .101, "#9b3fc4"),
			v(e + o - .28, e + o - .1, t + s - .38, t + s - .14, c + .101, "#d9b98a")
		] }) : v(e + o / 2 - .12, e + o / 2 + .12, t + .05, t + s - .05, c + .105, _(i.lid, 1.08))
	] });
}
function y(e, t) {
	let [n, r] = l([
		e,
		t,
		0
	]);
	return /* @__PURE__ */ (0, a.jsxs)("g", { children: [
		/* @__PURE__ */ (0, a.jsx)("rect", {
			x: n - 2,
			y: r - 26,
			width: 4,
			height: 26,
			rx: 2,
			fill: "#7a5a3a"
		}),
		/* @__PURE__ */ (0, a.jsx)("ellipse", {
			cx: n,
			cy: r - 44,
			rx: 15,
			ry: 24,
			fill: "#22b07d"
		}),
		/* @__PURE__ */ (0, a.jsx)("ellipse", {
			cx: n - 4,
			cy: r - 50,
			rx: 7,
			ry: 11,
			fill: "#3ccf96",
			opacity: .6
		})
	] }, `${e},${t}`);
}
var b = (e, t, n, r) => u(Array.from({ length: 16 }, (i, a) => [
	e + r * Math.cos(a * Math.PI / 8),
	t,
	n + r * Math.sin(a * Math.PI / 8)
]));
function x() {
	let e = 7.05, t = 8.35, n = 2.2, r = l([
		6.3,
		7.1499999999999995,
		2.75
	]);
	return /* @__PURE__ */ (0, a.jsxs)("g", {
		className: "truck",
		children: [
			g(2.3000000000000003, 7.4, 7.1499999999999995, 8.25, .32, .55, "#2b2f37", "#1d2027", "#3a3f48"),
			g(n, 5.7, e, t, .55, 2.35, "#2f9e5b", "#257d48", "#3cb96c"),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						n,
						8.355,
						.55
					],
					[
						5.7,
						8.355,
						.55
					],
					[
						5.7,
						8.355,
						.8
					],
					[
						n,
						8.355,
						.8
					]
				]),
				fill: "#e9eef5"
			}),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						2.35,
						8.355,
						1
					],
					[
						5.5,
						8.355,
						1
					],
					[
						5.5,
						8.355,
						2.1
					],
					[
						2.35,
						8.355,
						2.1
					]
				]),
				fill: "#38b26a"
			}),
			/* @__PURE__ */ (0, a.jsx)("text", {
				x: l([
					3.95,
					t,
					1.45
				])[0],
				y: l([
					3.95,
					t,
					1.45
				])[1],
				className: "truck-logo",
				transform: `rotate(30 ${l([
					3.95,
					t,
					1.45
				]).join(" ")})`,
				children: "VafabMiljö"
			}),
			g(5.800000000000001, 7.2, e, t, .55, 2, "#e9eef5", "#c9d3e0", "#f4f7fb"),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						7.21,
						7.2,
						1.2
					],
					[
						7.21,
						8.2,
						1.2
					],
					[
						7.21,
						8.2,
						1.85
					],
					[
						7.21,
						7.2,
						1.85
					]
				]),
				fill: "#9fd3f2"
			}),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						5.95,
						8.355,
						1.25
					],
					[
						6.8,
						8.355,
						1.25
					],
					[
						6.8,
						8.355,
						1.85
					],
					[
						5.95,
						8.355,
						1.85
					]
				]),
				fill: "#9fd3f2"
			}),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						7.21,
						8,
						.65
					],
					[
						7.21,
						8.23,
						.65
					],
					[
						7.21,
						8.23,
						.8
					],
					[
						7.21,
						8,
						.8
					]
				]),
				fill: "#fff3c4"
			}),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						2.8000000000000003,
						7.45,
						2.36
					],
					[
						3.2,
						7.45,
						2.36
					],
					[
						3.2,
						7.85,
						2.36
					],
					[
						2.8000000000000003,
						7.85,
						2.36
					]
				]),
				fill: "#f5b301"
			}),
			[
				2.9000000000000004,
				3.9000000000000004,
				6.5
			].map((e) => /* @__PURE__ */ (0, a.jsxs)("g", { children: [/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: b(e, 8.36, .38, .38),
				fill: "#15171b"
			}), /* @__PURE__ */ (0, a.jsx)("polygon", {
				points: b(e, 8.37, .38, .16),
				fill: "#9aa4b2"
			})] }, e)),
			g(6.2, 6.3500000000000005, 7.1, 7.25, 2, 2.75, "#6b7484", "#4a5262", "#8a96a8"),
			[
				0,
				1,
				2
			].map((e) => /* @__PURE__ */ (0, a.jsx)("circle", {
				cx: r[0],
				cy: r[1],
				r: 5,
				className: "smoke",
				style: { animationDelay: `${e * .8}s` }
			}, e))
		]
	});
}
function S({ bins: e, truck: t }) {
	let n = e.reduce((t, n, r) => [...t, r ? t[r - 1] + p(e[r - 1].type).w * h + .9 : -4.3], []), r = (e) => 6.8 - p(e.type).d * h;
	return /* @__PURE__ */ (0, a.jsxs)("svg", {
		viewBox: "0 0 640 400",
		className: "house-scene",
		role: "img",
		"aria-label": "house with waste bins",
		children: [
			/* @__PURE__ */ (0, a.jsxs)("defs", { children: [/* @__PURE__ */ (0, a.jsxs)("linearGradient", {
				id: "hs-wall",
				x1: "0",
				y1: "0",
				x2: "0",
				y2: "1",
				children: [/* @__PURE__ */ (0, a.jsx)("stop", {
					offset: "0%",
					stopColor: "#f4f7fb"
				}), /* @__PURE__ */ (0, a.jsx)("stop", {
					offset: "100%",
					stopColor: "#dde4ee"
				})]
			}), /* @__PURE__ */ (0, a.jsxs)("radialGradient", {
				id: "hs-ground",
				cx: "50%",
				cy: "50%",
				r: "50%",
				children: [/* @__PURE__ */ (0, a.jsx)("stop", {
					offset: "0%",
					stopColor: "var(--vm-accent)",
					stopOpacity: "0.16"
				}), /* @__PURE__ */ (0, a.jsx)("stop", {
					offset: "100%",
					stopColor: "var(--vm-accent)",
					stopOpacity: "0"
				})]
			})] }),
			/* @__PURE__ */ (0, a.jsx)("ellipse", {
				cx: l([
					3,
					4,
					0
				])[0],
				cy: l([
					3,
					4,
					0
				])[1],
				rx: 300,
				ry: 140,
				fill: "url(#hs-ground)"
			}),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						-4.8,
						-.5,
						0
					],
					[
						7.6,
						-.5,
						0
					],
					[
						7.6,
						6.9,
						0
					],
					[
						-4.8,
						6.9,
						0
					]
				]),
				className: "hs-plot"
			}),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						3.5,
						3.5,
						0
					],
					[
						4.5,
						3.5,
						0
					],
					[
						4.5,
						6.9,
						0
					],
					[
						3.5,
						6.9,
						0
					]
				]),
				className: "hs-path"
			}),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						-4.8,
						6.9,
						0
					],
					[
						7.6,
						6.9,
						0
					],
					[
						7.6,
						8.6,
						0
					],
					[
						-4.8,
						8.6,
						0
					]
				]),
				className: "hs-street"
			}),
			/* @__PURE__ */ (0, a.jsx)("polyline", {
				points: u([[
					-4.8,
					7.75,
					0
				], [
					7.6,
					7.75,
					0
				]]),
				className: "hs-lane"
			}),
			y(-3.6, 1.6),
			y(-2.4, .2),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						6,
						0,
						0
					],
					[
						6,
						3.5,
						0
					],
					[
						6,
						3.5,
						2.6
					],
					[
						6,
						1.75,
						4.3
					],
					[
						6,
						0,
						2.6
					]
				]),
				fill: "#c9d3e0",
				stroke: "#b7c2d1"
			}),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						0,
						3.5,
						0
					],
					[
						6,
						3.5,
						0
					],
					[
						6,
						3.5,
						2.6
					],
					[
						0,
						3.5,
						2.6
					]
				]),
				fill: "url(#hs-wall)",
				stroke: "#c3ccd8"
			}),
			[
				[.5, 1.4],
				[1.9, 2.8],
				[5, 5.6]
			].map(([e, t], n) => /* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						e,
						3.5,
						1.2
					],
					[
						t,
						3.5,
						1.2
					],
					[
						t,
						3.5,
						2.1
					],
					[
						e,
						3.5,
						2.1
					]
				]),
				className: "hs-window"
			}, n)),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						3.6,
						3.5,
						0
					],
					[
						4.4,
						3.5,
						0
					],
					[
						4.4,
						3.5,
						1.9
					],
					[
						3.6,
						3.5,
						1.9
					]
				]),
				fill: "#8a6a4a"
			}),
			[.8, 2.1].map((e, t) => /* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						6,
						e,
						1.2
					],
					[
						6,
						e + .7,
						1.2
					],
					[
						6,
						e + .7,
						2.1
					],
					[
						6,
						e,
						2.1
					]
				]),
				className: "hs-window side"
			}, t)),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						6.3,
						1.75,
						4.3
					],
					[
						6.3,
						-.4,
						2.45
					],
					[
						6.3,
						-.4,
						2.3
					],
					[
						6.3,
						1.75,
						4.15
					]
				]),
				fill: "#1d2027"
			}),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						-.3,
						3.9,
						2.45
					],
					[
						6.3,
						3.9,
						2.45
					],
					[
						6.3,
						1.75,
						4.3
					],
					[
						-.3,
						1.75,
						4.3
					]
				]),
				className: "hs-roof"
			}),
			/* @__PURE__ */ (0, a.jsx)("polygon", {
				points: u([
					[
						6.3,
						3.9,
						2.45
					],
					[
						6.3,
						3.9,
						2.3
					],
					[
						6.3,
						1.75,
						4.15
					],
					[
						6.3,
						1.75,
						4.3
					]
				]),
				fill: "#1d2027"
			}),
			y(7, 1.2),
			e.map((e, t) => /* @__PURE__ */ (0, a.jsx)(v, {
				x: n[t],
				y: r(e),
				type: e.type,
				glow: e.next
			}, e.type)),
			t && /* @__PURE__ */ (0, a.jsx)(x, {})
		]
	});
}
//#endregion
export { i as a, p as i, h as n, n as o, m as r, e as s, S as t };
