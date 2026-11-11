var q=globalThis,j=q.ShadowRoot&&(q.ShadyCSS===void 0||q.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,rt=Symbol(),St=new WeakMap,H=class{constructor(e,t,n){if(this._$cssResult$=!0,n!==rt)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=e,this.t=t}get styleSheet(){let e=this.o,t=this.t;if(j&&e===void 0){let n=t!==void 0&&t.length===1;n&&(e=St.get(t)),e===void 0&&((this.o=e=new CSSStyleSheet).replaceSync(this.cssText),n&&St.set(t,e))}return e}toString(){return this.cssText}},Pt=i=>new H(typeof i=="string"?i:i+"",void 0,rt),z=(i,...e)=>{let t=i.length===1?i[0]:e.reduce((n,s,o)=>n+(r=>{if(r._$cssResult$===!0)return r.cssText;if(typeof r=="number")return r;throw Error("Value passed to 'css' function must be a 'css' function result: "+r+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(s)+i[o+1],i[0]);return new H(t,i,rt)},Rt=(i,e)=>{if(j)i.adoptedStyleSheets=e.map(t=>t instanceof CSSStyleSheet?t:t.styleSheet);else for(let t of e){let n=document.createElement("style"),s=q.litNonce;s!==void 0&&n.setAttribute("nonce",s),n.textContent=t.cssText,i.appendChild(n)}},at=j?i=>i:i=>i instanceof CSSStyleSheet?(e=>{let t="";for(let n of e.cssRules)t+=n.cssText;return Pt(t)})(i):i;var{is:Ae,defineProperty:Ee,getOwnPropertyDescriptor:Te,getOwnPropertyNames:Se,getOwnPropertySymbols:Pe,getPrototypeOf:Re}=Object,B=globalThis,Dt=B.trustedTypes,De=Dt?Dt.emptyScript:"",Le=B.reactiveElementPolyfillSupport,O=(i,e)=>i,lt={toAttribute(i,e){switch(e){case Boolean:i=i?De:null;break;case Object:case Array:i=i==null?i:JSON.stringify(i)}return i},fromAttribute(i,e){let t=i;switch(e){case Boolean:t=i!==null;break;case Number:t=i===null?null:Number(i);break;case Object:case Array:try{t=JSON.parse(i)}catch{t=null}}return t}},Ht=(i,e)=>!Ae(i,e),Lt={attribute:!0,type:String,converter:lt,reflect:!1,useDefault:!1,hasChanged:Ht};Symbol.metadata??=Symbol("metadata"),B.litPropertyMetadata??=new WeakMap;var y=class extends HTMLElement{static addInitializer(e){this._$Ei(),(this.l??=[]).push(e)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(e,t=Lt){if(t.state&&(t.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(e)&&((t=Object.create(t)).wrapped=!0),this.elementProperties.set(e,t),!t.noAccessor){let n=Symbol(),s=this.getPropertyDescriptor(e,n,t);s!==void 0&&Ee(this.prototype,e,s)}}static getPropertyDescriptor(e,t,n){let{get:s,set:o}=Te(this.prototype,e)??{get(){return this[t]},set(r){this[t]=r}};return{get:s,set(r){let h=s?.call(this);o?.call(this,r),this.requestUpdate(e,h,n)},configurable:!0,enumerable:!0}}static getPropertyOptions(e){return this.elementProperties.get(e)??Lt}static _$Ei(){if(this.hasOwnProperty(O("elementProperties")))return;let e=Re(this);e.finalize(),e.l!==void 0&&(this.l=[...e.l]),this.elementProperties=new Map(e.elementProperties)}static finalize(){if(this.hasOwnProperty(O("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(O("properties"))){let t=this.properties,n=[...Se(t),...Pe(t)];for(let s of n)this.createProperty(s,t[s])}let e=this[Symbol.metadata];if(e!==null){let t=litPropertyMetadata.get(e);if(t!==void 0)for(let[n,s]of t)this.elementProperties.set(n,s)}this._$Eh=new Map;for(let[t,n]of this.elementProperties){let s=this._$Eu(t,n);s!==void 0&&this._$Eh.set(s,t)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(e){let t=[];if(Array.isArray(e)){let n=new Set(e.flat(1/0).reverse());for(let s of n)t.unshift(at(s))}else e!==void 0&&t.push(at(e));return t}static _$Eu(e,t){let n=t.attribute;return n===!1?void 0:typeof n=="string"?n:typeof e=="string"?e.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(e=>this.enableUpdating=e),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(e=>e(this))}addController(e){(this._$EO??=new Set).add(e),this.renderRoot!==void 0&&this.isConnected&&e.hostConnected?.()}removeController(e){this._$EO?.delete(e)}_$E_(){let e=new Map,t=this.constructor.elementProperties;for(let n of t.keys())this.hasOwnProperty(n)&&(e.set(n,this[n]),delete this[n]);e.size>0&&(this._$Ep=e)}createRenderRoot(){let e=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return Rt(e,this.constructor.elementStyles),e}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(e=>e.hostConnected?.())}enableUpdating(e){}disconnectedCallback(){this._$EO?.forEach(e=>e.hostDisconnected?.())}attributeChangedCallback(e,t,n){this._$AK(e,n)}_$ET(e,t){let n=this.constructor.elementProperties.get(e),s=this.constructor._$Eu(e,n);if(s!==void 0&&n.reflect===!0){let o=(n.converter?.toAttribute!==void 0?n.converter:lt).toAttribute(t,n.type);this._$Em=e,o==null?this.removeAttribute(s):this.setAttribute(s,o),this._$Em=null}}_$AK(e,t){let n=this.constructor,s=n._$Eh.get(e);if(s!==void 0&&this._$Em!==s){let o=n.getPropertyOptions(s),r=typeof o.converter=="function"?{fromAttribute:o.converter}:o.converter?.fromAttribute!==void 0?o.converter:lt;this._$Em=s;let h=r.fromAttribute(t,o.type);this[s]=h??this._$Ej?.get(s)??h,this._$Em=null}}requestUpdate(e,t,n,s=!1,o){if(e!==void 0){let r=this.constructor;if(s===!1&&(o=this[e]),n??=r.getPropertyOptions(e),!((n.hasChanged??Ht)(o,t)||n.useDefault&&n.reflect&&o===this._$Ej?.get(e)&&!this.hasAttribute(r._$Eu(e,n))))return;this.C(e,t,n)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(e,t,{useDefault:n,reflect:s,wrapped:o},r){n&&!(this._$Ej??=new Map).has(e)&&(this._$Ej.set(e,r??t??this[e]),o!==!0||r!==void 0)||(this._$AL.has(e)||(this.hasUpdated||n||(t=void 0),this._$AL.set(e,t)),s===!0&&this._$Em!==e&&(this._$Eq??=new Set).add(e))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(t){Promise.reject(t)}let e=this.scheduleUpdate();return e!=null&&await e,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[s,o]of this._$Ep)this[s]=o;this._$Ep=void 0}let n=this.constructor.elementProperties;if(n.size>0)for(let[s,o]of n){let{wrapped:r}=o,h=this[s];r!==!0||this._$AL.has(s)||h===void 0||this.C(s,void 0,o,h)}}let e=!1,t=this._$AL;try{e=this.shouldUpdate(t),e?(this.willUpdate(t),this._$EO?.forEach(n=>n.hostUpdate?.()),this.update(t)):this._$EM()}catch(n){throw e=!1,this._$EM(),n}e&&this._$AE(t)}willUpdate(e){}_$AE(e){this._$EO?.forEach(t=>t.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(e)),this.updated(e)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(e){return!0}update(e){this._$Eq&&=this._$Eq.forEach(t=>this._$ET(t,this[t])),this._$EM()}updated(e){}firstUpdated(e){}};y.elementStyles=[],y.shadowRootOptions={mode:"open"},y[O("elementProperties")]=new Map,y[O("finalized")]=new Map,Le?.({ReactiveElement:y}),(B.reactiveElementVersions??=[]).push("2.1.2");var ct=globalThis,zt=i=>i,F=ct.trustedTypes,Ot=F?F.createPolicy("lit-html",{createHTML:i=>i}):void 0,ht="$lit$",$=`lit$${Math.random().toFixed(9).slice(2)}$`,ut="?"+$,He=`<${ut}>`,C=document,V=()=>C.createComment(""),M=i=>i===null||typeof i!="object"&&typeof i!="function",pt=Array.isArray,qt=i=>pt(i)||typeof i?.[Symbol.iterator]=="function",dt=`[ 	
\f\r]`,N=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,Nt=/-->/g,Vt=/>/g,b=RegExp(`>|${dt}(?:([^\\s"'>=/]+)(${dt}*=${dt}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),Mt=/'/g,Ut=/"/g,jt=/^(?:script|style|textarea|title)$/i,_t=i=>(e,...t)=>({_$litType$:i,strings:e,values:t}),a=_t(1),li=_t(2),di=_t(3),x=Symbol.for("lit-noChange"),l=Symbol.for("lit-nothing"),It=new WeakMap,w=C.createTreeWalker(C,129);function Bt(i,e){if(!pt(i)||!i.hasOwnProperty("raw"))throw Error("invalid template strings array");return Ot!==void 0?Ot.createHTML(e):e}var Ft=(i,e)=>{let t=i.length-1,n=[],s,o=e===2?"<svg>":e===3?"<math>":"",r=N;for(let h=0;h<t;h++){let d=i[h],u,p,c=-1,_=0;for(;_<d.length&&(r.lastIndex=_,p=r.exec(d),p!==null);)_=r.lastIndex,r===N?p[1]==="!--"?r=Nt:p[1]!==void 0?r=Vt:p[2]!==void 0?(jt.test(p[2])&&(s=RegExp("</"+p[2],"g")),r=b):p[3]!==void 0&&(r=b):r===b?p[0]===">"?(r=s??N,c=-1):p[1]===void 0?c=-2:(c=r.lastIndex-p[2].length,u=p[1],r=p[3]===void 0?b:p[3]==='"'?Ut:Mt):r===Ut||r===Mt?r=b:r===Nt||r===Vt?r=N:(r=b,s=void 0);let m=r===b&&i[h+1].startsWith("/>")?" ":"";o+=r===N?d+He:c>=0?(n.push(u),d.slice(0,c)+ht+d.slice(c)+$+m):d+$+(c===-2?h:m)}return[Bt(i,o+(i[t]||"<?>")+(e===2?"</svg>":e===3?"</math>":"")),n]},U=class i{constructor({strings:e,_$litType$:t},n){let s;this.parts=[];let o=0,r=0,h=e.length-1,d=this.parts,[u,p]=Ft(e,t);if(this.el=i.createElement(u,n),w.currentNode=this.el.content,t===2||t===3){let c=this.el.content.firstChild;c.replaceWith(...c.childNodes)}for(;(s=w.nextNode())!==null&&d.length<h;){if(s.nodeType===1){if(s.hasAttributes())for(let c of s.getAttributeNames())if(c.endsWith(ht)){let _=p[r++],m=s.getAttribute(c).split($),T=/([.?@])?(.*)/.exec(_);d.push({type:1,index:o,name:T[2],strings:m,ctor:T[1]==="."?G:T[1]==="?"?K:T[1]==="@"?Q:A}),s.removeAttribute(c)}else c.startsWith($)&&(d.push({type:6,index:o}),s.removeAttribute(c));if(jt.test(s.tagName)){let c=s.textContent.split($),_=c.length-1;if(_>0){s.textContent=F?F.emptyScript:"";for(let m=0;m<_;m++)s.append(c[m],V()),w.nextNode(),d.push({type:2,index:++o});s.append(c[_],V())}}}else if(s.nodeType===8)if(s.data===ut)d.push({type:2,index:o});else{let c=-1;for(;(c=s.data.indexOf($,c+1))!==-1;)d.push({type:7,index:o}),c+=$.length-1}o++}}static createElement(e,t){let n=C.createElement("template");return n.innerHTML=e,n}};function k(i,e,t=i,n){if(e===x)return e;let s=n!==void 0?t._$Co?.[n]:t._$Cl,o=M(e)?void 0:e._$litDirective$;return s?.constructor!==o&&(s?._$AO?.(!1),o===void 0?s=void 0:(s=new o(i),s._$AT(i,t,n)),n!==void 0?(t._$Co??=[])[n]=s:t._$Cl=s),s!==void 0&&(e=k(i,s._$AS(i,e.values),s,n)),e}var W=class{constructor(e,t){this._$AV=[],this._$AN=void 0,this._$AD=e,this._$AM=t}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(e){let{el:{content:t},parts:n}=this._$AD,s=(e?.creationScope??C).importNode(t,!0);w.currentNode=s;let o=w.nextNode(),r=0,h=0,d=n[0];for(;d!==void 0;){if(r===d.index){let u;d.type===2?u=new S(o,o.nextSibling,this,e):d.type===1?u=new d.ctor(o,d.name,d.strings,this,e):d.type===6&&(u=new Y(o,this,e)),this._$AV.push(u),d=n[++h]}r!==d?.index&&(o=w.nextNode(),r++)}return w.currentNode=C,s}p(e){let t=0;for(let n of this._$AV)n!==void 0&&(n.strings!==void 0?(n._$AI(e,n,t),t+=n.strings.length-2):n._$AI(e[t])),t++}},S=class i{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(e,t,n,s){this.type=2,this._$AH=l,this._$AN=void 0,this._$AA=e,this._$AB=t,this._$AM=n,this.options=s,this._$Cv=s?.isConnected??!0}get parentNode(){let e=this._$AA.parentNode,t=this._$AM;return t!==void 0&&e?.nodeType===11&&(e=t.parentNode),e}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(e,t=this){e=k(this,e,t),M(e)?e===l||e==null||e===""?(this._$AH!==l&&this._$AR(),this._$AH=l):e!==this._$AH&&e!==x&&this._(e):e._$litType$!==void 0?this.$(e):e.nodeType!==void 0?this.T(e):qt(e)?this.k(e):this._(e)}O(e){return this._$AA.parentNode.insertBefore(e,this._$AB)}T(e){this._$AH!==e&&(this._$AR(),this._$AH=this.O(e))}_(e){this._$AH!==l&&M(this._$AH)?this._$AA.nextSibling.data=e:this.T(C.createTextNode(e)),this._$AH=e}$(e){let{values:t,_$litType$:n}=e,s=typeof n=="number"?this._$AC(e):(n.el===void 0&&(n.el=U.createElement(Bt(n.h,n.h[0]),this.options)),n);if(this._$AH?._$AD===s)this._$AH.p(t);else{let o=new W(s,this),r=o.u(this.options);o.p(t),this.T(r),this._$AH=o}}_$AC(e){let t=It.get(e.strings);return t===void 0&&It.set(e.strings,t=new U(e)),t}k(e){pt(this._$AH)||(this._$AH=[],this._$AR());let t=this._$AH,n,s=0;for(let o of e)s===t.length?t.push(n=new i(this.O(V()),this.O(V()),this,this.options)):n=t[s],n._$AI(o),s++;s<t.length&&(this._$AR(n&&n._$AB.nextSibling,s),t.length=s)}_$AR(e=this._$AA.nextSibling,t){for(this._$AP?.(!1,!0,t);e!==this._$AB;){let n=zt(e).nextSibling;zt(e).remove(),e=n}}setConnected(e){this._$AM===void 0&&(this._$Cv=e,this._$AP?.(e))}},A=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(e,t,n,s,o){this.type=1,this._$AH=l,this._$AN=void 0,this.element=e,this.name=t,this._$AM=s,this.options=o,n.length>2||n[0]!==""||n[1]!==""?(this._$AH=Array(n.length-1).fill(new String),this.strings=n):this._$AH=l}_$AI(e,t=this,n,s){let o=this.strings,r=!1;if(o===void 0)e=k(this,e,t,0),r=!M(e)||e!==this._$AH&&e!==x,r&&(this._$AH=e);else{let h=e,d,u;for(e=o[0],d=0;d<o.length-1;d++)u=k(this,h[n+d],t,d),u===x&&(u=this._$AH[d]),r||=!M(u)||u!==this._$AH[d],u===l?e=l:e!==l&&(e+=(u??"")+o[d+1]),this._$AH[d]=u}r&&!s&&this.j(e)}j(e){e===l?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,e??"")}},G=class extends A{constructor(){super(...arguments),this.type=3}j(e){this.element[this.name]=e===l?void 0:e}},K=class extends A{constructor(){super(...arguments),this.type=4}j(e){this.element.toggleAttribute(this.name,!!e&&e!==l)}},Q=class extends A{constructor(e,t,n,s,o){super(e,t,n,s,o),this.type=5}_$AI(e,t=this){if((e=k(this,e,t,0)??l)===x)return;let n=this._$AH,s=e===l&&n!==l||e.capture!==n.capture||e.once!==n.once||e.passive!==n.passive,o=e!==l&&(n===l||s);s&&this.element.removeEventListener(this.name,this,n),o&&this.element.addEventListener(this.name,this,e),this._$AH=e}handleEvent(e){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,e):this._$AH.handleEvent(e)}},Y=class{constructor(e,t,n){this.element=e,this.type=6,this._$AN=void 0,this._$AM=t,this.options=n}get _$AU(){return this._$AM._$AU}_$AI(e){k(this,e)}},Wt={M:ht,P:$,A:ut,C:1,L:Ft,R:W,D:qt,V:k,I:S,H:A,N:K,U:Q,B:G,F:Y},ze=ct.litHtmlPolyfillSupport;ze?.(U,S),(ct.litHtmlVersions??=[]).push("3.3.3");var Gt=(i,e,t)=>{let n=t?.renderBefore??e,s=n._$litPart$;if(s===void 0){let o=t?.renderBefore??null;n._$litPart$=s=new S(e.insertBefore(V(),o),o,void 0,t??{})}return s._$AI(i),s};var mt=globalThis,f=class extends y{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let e=super.createRenderRoot();return this.renderOptions.renderBefore??=e.firstChild,e}update(e){let t=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(e),this._$Do=Gt(t,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return x}};f._$litElement$=!0,f.finalized=!0,mt.litElementHydrateSupport?.({LitElement:f});var Oe=mt.litElementPolyfillSupport;Oe?.({LitElement:f});(mt.litElementVersions??=[]).push("4.2.2");var Kt=i=>(...e)=>({_$litDirective$:i,values:e}),Z=class{constructor(e){}get _$AU(){return this._$AM._$AU}_$AT(e,t,n){this._$Ct=e,this._$AM=t,this._$Ci=n}_$AS(e,t){return this.update(e,t)}update(e,t){return this.render(...t)}};var{I:xi}=Wt;var Ne={},Qt=(i,e=Ne)=>i._$AH=e;var Yt=Kt(class extends Z{constructor(){super(...arguments),this.key=l}render(i,e){return this.key=i,e}update(i,[e,t]){return e!==this.key&&(Qt(i),this.key=e),t}});function Zt(i){return i.callWS({type:"siipet/cats"})}function Jt(i,e,t){return i.callWS({type:"siipet/day",date:e,cat:t})}function Xt(i){return i.callWS({type:"siipet/queue"})}function te(i,e){return i.callWS({type:"siipet/visit",event_id:e})}function ee(i,e,t){return i.callWS({type:"siipet/calendar",month:e,cat:t})}async function ie(i,e){return(await i.callWS({type:"media_source/resolve_media",media_content_id:`media-source://siipet/visit/${e}`})).url}function ne(i,e){return i.callService("siipet","update_visit",e,void 0,!1)}function se(i,e){return i.callService("siipet","delete_visit",{event_id:e},void 0,!1)}function oe(i,e){if(typeof i!="object"||i===null)return;if(e in i)return i[e];let t=i.error;return typeof t=="object"&&t!==null&&e in t?t[e]:void 0}function J(i,e){let t=oe(i,e);return typeof t=="string"&&t!==""?t:void 0}function X(i){return J(i,"translation_key")}function P(i,e){let t=X(i);if(t!==void 0&&e.localize&&J(i,"translation_domain")==="siipet"){let n=oe(i,"translation_placeholders"),s=e.localize(`component.siipet.exceptions.${t}.message`,typeof n=="object"&&n!==null?n:void 0);if(s)return s}return J(i,"message")??e.text.requestFailed}function re(i){return X(i)==="edit_partial"}function ae(i){return X(i)==="visit_not_in_window"}function le(i){return J(i,"code")==="service_validation_error"&&X(i)!=="not_loaded"}function de(i,e,t,n){let[s,o]=i.split("-").map(Number),r=new Date(Date.UTC(s,o-1,1)),h=new Date(Date.UTC(s,o,0)).getUTCDate(),d=(r.getUTCDay()-n+7)%7,u=Array.from({length:d},()=>({date:null}));for(let p=1;p<=h;p++){let c=`${i}-${String(p).padStart(2,"0")}`;u.push({date:c,day:p,marked:e?.days[c]?.marked??!1,openable:e!==null&&e.first<=c&&c<=e.last,selected:c===t})}return u}var Ve=["sunday","monday","tuesday","wednesday","thursday","friday","saturday"];function tt(i){let[e,t,n]=i.split("-").map(Number);return new Date(Date.UTC(e,t-1,n))}function ce(i){return i.toISOString().slice(0,10)}function et(i,e,t){return new Intl.DateTimeFormat(i.language,{...e,calendar:"gregory",timeZone:"UTC"}).format(t)}function g(i,e){return et(e,{weekday:"short",month:"short",day:"numeric"},tt(i))}function he(i,e){return et(e,{month:"long",year:"numeric"},tt(`${i}-01`))}function Me(i){if(i.time_format==="12"||i.time_format==="24")return i.time_format==="12";let e=i.time_format==="system"?void 0:i.language;return new Date("January 1, 2023 22:00:00").toLocaleString(e).includes("10")}function R(i,e){let[t,n]=i.slice(11,16).split(":").map(Number),s=Me(e);return et(e,{hour:"numeric",minute:"2-digit",hourCycle:s?"h12":"h23"},new Date(Date.UTC(1970,0,1,t,n)))}function ft(i){let e=Ve.indexOf(i.first_weekday??"language");if(e>=0)return e;try{let t=new Intl.Locale(i.language),n=t.getWeekInfo?.()??t.weekInfo;if(n)return n.firstDay%7}catch{}return 1}function ue(i){let e=ft(i);return Array.from({length:7},(t,n)=>et(i,{weekday:"short"},new Date(Date.UTC(2023,0,1+(e+n)%7))))}function it(i){let e=Math.floor(i/60),t=i%60;return e===0?`${t} s`:t===0?`${e} min`:`${e} min ${t} s`}function gt(i,e){let t=tt(i);return t.setUTCDate(t.getUTCDate()+e),ce(t)}function v(i){return i.slice(0,7)}function vt(i,e){let t=tt(`${i}-01`);return t.setUTCMonth(t.getUTCMonth()+e),ce(t).slice(0,7)}var nt={poop:{icon:"mdi:emoticon-poop",color:"var(--brown-color)"},pee:{icon:"mdi:water",color:"var(--amber-color)"},lingering:{icon:"mdi:paw",color:"var(--grey-color)"},unknown:{icon:"mdi:help",color:"var(--disabled-color)"}};var Ue="display: inline-flex; align-items: center; gap: 6px; max-width: 100%; width: auto; white-space: nowrap",Ie="overflow: hidden; text-overflow: ellipsis; min-width: 0; width: auto";function I(i,e){return a`<span style=${Ue}
    >${i}<span style=${Ie}>${e}</span></span
  >`}function pe(i,e,t){let n=t.text,s=[g(i,t.locale),n.visits(e.visits)];return e.poop>0&&s.push(n.poop(e.poop)),e.pee>0&&s.push(n.pee(e.pee)),e.abnormal>0&&s.push(n.abnormal(e.abnormal)),s.join(" \xB7 ")}function _e(i,e){return e.text.waiting(i)}function yt(i){return a`
    <ha-tile-container class="header">
      <ha-tile-icon slot="icon" .imageUrl=${i.imageUrl} .icon=${i.icon}></ha-tile-icon>
      <ha-tile-info slot="info">
        <span slot="primary">${i.primary}</span>
        <span slot="secondary">${i.secondary}</span>
      </ha-tile-info>
      <div slot="features" class="features">${i.features}</div>
    </ha-tile-container>
  `}function me(i){return a`
    <ha-control-button-group class="date-bar">
      <ha-control-button
        class="arrow prev-day"
        .label=${i.l10n.text.previousDay}
        .disabled=${!i.canGoBack}
        @click=${()=>i.onShift(-1)}
      >
        <ha-icon icon="mdi:chevron-left"></ha-icon>
      </ha-control-button>
      <ha-control-button
        class="date"
        .label=${i.l10n.text.pickDay}
        @click=${i.onToggle}
      >
        <span>${g(i.date,i.l10n.locale)}</span>
        ${i.marked?a`<span class="dot"></span>`:l}
      </ha-control-button>
      <ha-control-button
        class="arrow next-day"
        .label=${i.l10n.text.nextDay}
        .disabled=${!i.canGoForward}
        @click=${()=>i.onShift(1)}
      >
        <ha-icon icon="mdi:chevron-right"></ha-icon>
      </ha-control-button>
    </ha-control-button-group>
  `}function fe(i){let e=de(i.month,i.calendar??null,i.selected,ft(i.l10n.locale));return a`
    <div class="calendar">
      <ha-control-button-group class="month-bar">
        <ha-control-button
          class="arrow prev-month"
          .label=${i.l10n.text.previousMonth}
          .disabled=${!i.canGoBack}
          @click=${()=>i.onShiftMonth(-1)}
        >
          <ha-icon icon="mdi:chevron-left"></ha-icon>
        </ha-control-button>
        <div class="month-name">${he(i.month,i.l10n.locale)}</div>
        <ha-control-button
          class="arrow next-month"
          .label=${i.l10n.text.nextMonth}
          .disabled=${!i.canGoForward}
          @click=${()=>i.onShiftMonth(1)}
        >
          <ha-icon icon="mdi:chevron-right"></ha-icon>
        </ha-control-button>
      </ha-control-button-group>
      <div class="grid">
        ${ue(i.l10n.locale).map(t=>a`<span class="weekday">${t}</span>`)}
        ${e.map(t=>t.date===null?a`<span class="blank"></span>`:a`
                <ha-control-button
                  class="cell ${t.selected?"selected":""}"
                  data-date=${t.date}
                  .label=${g(t.date,i.l10n.locale)}
                  .disabled=${!t.openable}
                  @click=${()=>i.onOpenDay(t.date)}
                >
                  <span>${t.day}</span>
                  ${t.marked?a`<span class="dot"></span>`:l}
                </ha-control-button>
              `)}
      </div>
    </div>
  `}var qe="width: 20px; height: 20px; border-radius: 50%; object-fit: cover; flex: none";function ge(i,e,t,n,s){if(t)return l;let o=i.cats.map(r=>({value:r.device_id,ariaLabel:r.name,icon:I(r.avatar?a`<img src=${r.avatar} alt="" style=${qe} />`:a`<ha-icon icon="mdi:cat"></ha-icon>`,r.name)}));if(i.unknown.waiting>0){let r=s.text.unknownOption(i.unknown.waiting);o.push({value:i.unknown.device_id,ariaLabel:r,icon:I(a`<ha-icon icon="mdi:help"></ha-icon>`,r)})}return o.length<2?l:a`
    <ha-control-select
      class="cats"
      .options=${o}
      .value=${e}
      .label=${s.text.cat}
      @value-changed=${r=>{r.stopPropagation(),n(r.detail.value)}}
    ></ha-control-select>
  `}function je(i,e,t,n){let s=nt[i.type],o=R(i.start,n.locale),r=e?`${g(i.start.slice(0,10),n.locale)} ${o}`:o,h=`${n.text.types[i.type]} \xB7 ${it(i.duration)}`,d=i.camera?` \xB7 ${i.camera}`:"",u=i.note?a`<ha-icon class="memo" icon="mdi:note-text-outline"></ha-icon>`:l,p=i.abnormal_reasons[0]??n.text.abnormalChip,c=i.abnormal?a`<span slot="features-inline" class="chip">${p}</span>`:l,_=i.cover?a`<img class="cover" src=${i.cover} alt="" loading="lazy" />`:l,m=i.stool?a`<div class="stool-row">
        <ha-icon icon="mdi:camera-outline"></ha-icon>
        <span class="stool-label">${n.text.stoolPhoto}</span>
        <img class="stool" src=${i.stool} alt=${n.text.stoolPhoto} loading="lazy" />
      </div>`:l,T=i.has_video?l:a`<span class="camera-only">${n.text.onCameraOnly}</span>`;return a`
    <ha-tile-container
      class="visit ${i.type}"
      data-event=${i.event_id}
      .interactive=${!0}
      @action=${()=>t(i)}
    >
      <ha-tile-icon
        slot="icon"
        .icon=${s.icon}
        style="--tile-icon-color: ${s.color}"
      ></ha-tile-icon>
      <ha-tile-info slot="info">
        <span slot="primary">${r}</span>
        <span slot="secondary">${h} ${u}${d}</span>
      </ha-tile-info>
      ${c}
      <div slot="features" class="poster-slot">
        <div class="poster">${_} ${T}</div>
        ${m}
      </div>
    </ha-tile-container>
  `}function $t(i,e,t,n){if(i===void 0)return l;if(i.length===0){let s=e?n.text.noVisitsWaiting:n.text.noVisitsOnDay;return a`<div class="message empty">${s}</div>`}return a`<div class="timeline">
    ${i.map(s=>je(s,e,t,n))}
  </div>`}function bt(i){return{cats:i.cats.flatMap(e=>e.device_id?[e.device_id]:[]),type:i.type==="unknown"?null:i.type,note:i.note}}function Be(i,e){return i.length===e.length&&i.every(t=>e.includes(t))}function ve(i,e,t={}){let n=bt(i),s={event_id:i.event_id},o=!Be(n.cats,e.cats);if(o){if(e.cats.length===0)return{data:null,reason:"no_cat"};s.cats=e.cats}if(e.type!==null&&(t.sendType||e.type!==n.type)&&(s.type=e.type),o&&i.type==="unknown"&&s.type===void 0)return{data:null,reason:"type_required"};let r=e.note.trim();return r!==i.note&&(s.note=r),Object.keys(s).length===1?{data:null,reason:"no_change"}:{data:s,reason:null}}function wt(i,e,t,n){if(i===1)return e;let s=i%10,o=i%100;return s>=2&&s<=4&&(o<12||o>14)?t:n}var ye=i=>`${i} ${i===1?"visit":"visits"}`,$e=i=>`${i} ${wt(i,"wizyta","wizyty","wizyt")}`,Fe={types:{pee:"Pee",poop:"Poop",lingering:"Lingering",unknown:"Unknown"},previousDay:"Previous day",nextDay:"Next day",pickDay:"Pick a day",previousMonth:"Previous month",nextMonth:"Next month",cat:"Cat",unknown:"Unknown",unknownOption:i=>`Unknown (${i})`,visits:ye,poop:i=>`${i} poop`,pee:i=>`${i} pee`,abnormal:i=>`${i} abnormal`,waiting:i=>`${ye(i)} waiting`,abnormalChip:"Abnormal",stoolPhoto:"Stool photo",onCameraOnly:"On camera only",noVisitsWaiting:"No visits are waiting.",noVisitsOnDay:"No visits on this day.",catGone:"The cat of this card is not in the SiiPet account.",noCats:"The SiiPet account has no cats.",notUpdating:i=>`SiiPet is not updating. Last update: ${i}.`,missingParts:i=>`The card cannot start. The Home Assistant frontend has no ${i}.`,requestFailed:"The request failed.",deleteTitle:"Delete this visit?",deleteText:"SiiPet deletes the visit and its recording. You cannot undo this.",delete:"Delete",cancel:"Cancel",save:"Save",type:"Type",memo:"Memo",pickType:"Pick a type as well.",recordingOnCamera:"Recording is on the camera only.",cannotPlay:"This browser cannot play the recording. Safari and the Home Assistant app can.",close:"Close",configCat:"Cat",configCatHelper:"Optional. Without a cat, the card starts with the first cat.",configHideCatPicker:"Hide the cat picker",configHideCatPickerHelper:"Keep the card on one cat.",configCatInvalid:"The cat option must be a device ID.",configHideCatPickerInvalid:"The hide_cat_picker option must be true or false.",pickerName:"SiiPet visits",pickerDescription:"The litter box visits of each cat, day by day."},We={types:{pee:"Siku",poop:"Kupa",lingering:"Bez za\u0142atwienia",unknown:"Nieznany"},previousDay:"Poprzedni dzie\u0144",nextDay:"Nast\u0119pny dzie\u0144",pickDay:"Wybierz dzie\u0144",previousMonth:"Poprzedni miesi\u0105c",nextMonth:"Nast\u0119pny miesi\u0105c",cat:"Kot",unknown:"Nieznany",unknownOption:i=>`Nieznany (${i})`,visits:$e,poop:i=>`${i} ${wt(i,"kupa","kupy","kup")}`,pee:i=>`${i} siku`,abnormal:i=>`${i} ${wt(i,"nieprawid\u0142owa","nieprawid\u0142owe","nieprawid\u0142owych")}`,waiting:i=>`${$e(i)} do przypisania`,abnormalChip:"Nieprawid\u0142owa",stoolPhoto:"Zdj\u0119cie kupy",onCameraOnly:"Tylko w kamerze",noVisitsWaiting:"Brak wizyt do przypisania.",noVisitsOnDay:"Brak wizyt tego dnia.",catGone:"Kota wybranego dla tej karty nie ma na koncie SiiPet.",noCats:"Na koncie SiiPet nie ma kot\xF3w.",notUpdating:i=>`SiiPet nie aktualizuje danych. Ostatnia aktualizacja: ${i}.`,missingParts:i=>`Karta nie mo\u017Ce si\u0119 uruchomi\u0107. W interfejsie Home Assistant brakuje: ${i}.`,requestFailed:"\u017B\u0105danie nie powiod\u0142o si\u0119.",deleteTitle:"Usun\u0105\u0107 t\u0119 wizyt\u0119?",deleteText:"SiiPet usunie wizyt\u0119 i jej nagranie. Tego nie mo\u017Cna cofn\u0105\u0107.",delete:"Usu\u0144",cancel:"Anuluj",save:"Zapisz",type:"Typ",memo:"Notatka",pickType:"Wybierz te\u017C typ.",recordingOnCamera:"Nagranie jest tylko w kamerze.",cannotPlay:"Ta przegl\u0105darka nie odtworzy nagrania. Safari i aplikacja Home Assistant to potrafi\u0105.",close:"Zamknij",configCat:"Kot",configCatHelper:"Opcjonalnie. Bez kota karta zaczyna od pierwszego kota.",configHideCatPicker:"Ukryj wyb\xF3r kota",configHideCatPickerHelper:"Karta zostaje przy jednym kocie.",configCatInvalid:"Opcja cat musi by\u0107 identyfikatorem urz\u0105dzenia.",configHideCatPickerInvalid:"Opcja hide_cat_picker musi mie\u0107 warto\u015B\u0107 true lub false.",pickerName:"Wizyty SiiPet",pickerDescription:"Wizyty ka\u017Cdego kota w kuwecie, dzie\u0144 po dniu."};function E(i){return i?.split("-")[0].toLowerCase()==="pl"?We:Fe}function D(){return document.documentElement.lang}function L(i){let e=i?.locale?.language??i?.language??"en";return{locale:{...i?.locale,language:e},text:E(e),localize:i?.localize}}function be(i){let{locale:e}=L(i);return`${e.language}|${e.time_format??""}|${e.first_weekday??""}`}var st=z`
  ha-card {
    height: 100%;
    overflow: hidden;
  }
  /* The tap area of a tile row is absolutely positioned, so each row must hold its own. */
  ha-tile-container {
    position: relative;
    height: auto;
  }
  ha-tile-icon {
    --tile-icon-color: var(--tile-color);
  }
  .features {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  ha-control-button-group {
    --control-button-group-spacing: 12px;
    --control-button-group-thickness: 42px;
  }
  ha-control-button {
    --control-button-border-radius: var(--ha-border-radius-lg, 12px);
    --control-button-focus-color: var(--tile-color);
  }
  ha-control-button.arrow {
    flex: 0 0 42px;
  }
  .date {
    font-weight: var(--ha-font-weight-medium, 500);
  }
  .dot {
    width: 6px;
    height: 6px;
    margin-left: 6px;
    border-radius: 50%;
    background-color: var(--error-color);
  }
  .calendar {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .month-name {
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: var(--ha-font-weight-medium, 500);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 4px;
  }
  .weekday {
    text-align: center;
    font-size: var(--ha-font-size-s, 12px);
    color: var(--secondary-text-color);
  }
  ha-control-button.cell {
    position: relative;
    width: 100%;
    height: 36px;
    --control-button-border-radius: var(--ha-border-radius-md, 8px);
    --control-button-padding: 0;
  }
  ha-control-button.cell.selected {
    --control-button-background-color: var(--tile-color);
    --control-button-background-opacity: 1;
    --control-button-icon-color: white;
  }
  .cell .dot {
    position: absolute;
    bottom: 4px;
    left: 50%;
    margin: 0;
    transform: translateX(-50%);
  }
  ha-control-select {
    --control-select-color: var(--tile-color);
    --control-select-thickness: 42px;
    --control-select-border-radius: var(--ha-border-radius-lg, 12px);
  }
  .notice,
  .error {
    margin: 0 12px 12px;
    padding: 8px 12px;
    border-radius: var(--ha-border-radius-md, 8px);
    background-color: color-mix(in srgb, var(--warning-color) 20%, transparent);
  }
  .notice {
    margin-top: 12px;
  }
  .message {
    padding: 0 12px 12px;
    color: var(--secondary-text-color);
  }
  .message.alone {
    padding-top: 12px;
  }
  .visit.lingering {
    opacity: 0.6;
  }
  .memo {
    --mdc-icon-size: 14px;
  }
  .chip {
    align-self: center;
    margin-right: 10px;
    padding: 2px 8px;
    border-radius: var(--ha-border-radius-pill, 9999px);
    font-size: var(--ha-font-size-s, 12px);
    font-weight: var(--ha-font-weight-medium, 500);
    white-space: nowrap;
    color: var(--error-color);
    background-color: color-mix(in srgb, var(--error-color) 20%, transparent);
  }
  /* ha-tile-container pads its features slot, so the poster's background and
     radius would sit inside that padding instead of filling the row; a plain
     wrapper takes the slot and padding, and the poster box fills the wrapper.
     Taps on the wrapper and everything in it, the stool row too, pass through
     to the tap area of the row. */
  .poster-slot {
    pointer-events: none;
  }
  .poster {
    position: relative;
    pointer-events: none;
    aspect-ratio: 16 / 9;
    overflow: hidden;
    border-radius: var(--ha-border-radius-lg, 12px);
    background-color: var(--secondary-background-color);
  }
  .lingering .poster-slot {
    width: 50%;
  }
  .cover {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center;
  }
  .stool-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 8px;
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-m, 14px);
    --mdc-icon-size: 18px;
  }
  .stool-label {
    flex: 1;
  }
  .stool {
    display: block;
    height: 56px;
    width: auto;
    max-width: 40%;
    object-fit: contain;
    border-radius: var(--ha-border-radius-md, 8px);
  }
  .camera-only {
    position: absolute;
    left: 8px;
    bottom: 8px;
    padding: 2px 8px;
    border-radius: var(--ha-border-radius-pill, 9999px);
    font-size: var(--ha-font-size-s, 12px);
    color: white;
    background-color: rgba(0, 0, 0, 0.6);
  }
`;var we=200,Ge=["pee","poop","lingering"],Ct=class extends f{constructor(){super();this._resolveSeq=0;this.cats=[],this.l10n=L(void 0),this._busy=!1,this._partialEdit=!1}static{this.properties={hass:{attribute:!1},visit:{attribute:!1},cats:{attribute:!1},l10n:{attribute:!1},_baseline:{state:!0},_form:{state:!0},_video:{state:!0},_videoNote:{state:!0},_error:{state:!0},_busy:{state:!0},_partialEdit:{state:!0},_stoolDialogSrc:{state:!0}}}static{this.styles=[st,z`
      :host {
        display: block;
      }
      .editor {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 0 12px 12px;
      }
      /* The box takes the full width, the same as the timeline poster, and its
         height comes from the aspect ratio and the max height. So it holds its
         size before the recording loads (preload="none" leaves no intrinsic size
         to lay out from). Where the max height wins, object-fit crops the top
         and bottom of the recording. */
      video {
        display: block;
        width: 100%;
        max-height: 70vh;
        aspect-ratio: 9 / 16;
        object-fit: cover;
        border-radius: var(--ha-border-radius-lg, 12px);
        background-color: black;
      }
      video:fullscreen {
        object-fit: contain;
      }
      .video-note,
      .hint,
      .reasons {
        color: var(--secondary-text-color);
      }
      .stool-row {
        display: flex;
        align-items: center;
        gap: 12px;
        --mdc-icon-size: 20px;
      }
      .stool-row[role="button"] {
        cursor: zoom-in;
      }
      .stool-row ha-icon {
        color: var(--secondary-text-color);
      }
      .stool-text {
        flex: 1;
        min-width: 0;
      }
      .stool-photo {
        display: block;
        height: 56px;
        width: auto;
        max-width: 40%;
        object-fit: contain;
        border-radius: var(--ha-border-radius-md, 8px);
      }
      .stool-label {
        color: var(--primary-text-color);
        font-size: var(--ha-font-size-m, 14px);
        font-weight: var(--ha-font-weight-medium, 500);
      }
      .stool-dialog {
        width: 100vw;
        height: 100vh;
        max-width: 100vw;
        max-height: 100vh;
        margin: 0;
        padding: 0;
        border: none;
        background: black;
      }
      .stool-dialog:not([open]) {
        display: none;
      }
      .stool-dialog[open] {
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .stool-dialog::backdrop {
        background: black;
      }
      /* In the Home Assistant apps for iOS and macOS, an image can report the
         size it was first drawn at as its natural size. The stool photo is
         drawn first as the thumbnail, so the enlarged photo takes the box of
         the dialog and not a size of its own. */
      .stool-dialog-photo {
        width: 100%;
        height: 100%;
        object-fit: contain;
      }
      .stool-dialog-close {
        position: fixed;
        top: 0;
        right: 0;
        width: 48px;
        height: 48px;
        display: flex;
        align-items: center;
        justify-content: center;
        border: none;
        padding: 0;
        color: white;
        background: transparent;
        cursor: pointer;
      }
      ha-control-button.cat img {
        width: 20px;
        height: 20px;
        margin-right: 6px;
        border-radius: 50%;
        object-fit: cover;
      }
      ha-control-button.cat.on,
      ha-control-button.save {
        --control-button-background-color: var(--tile-color);
        --control-button-background-opacity: 1;
        --control-button-icon-color: white;
      }
      ha-control-button.delete {
        --control-button-icon-color: var(--error-color);
      }
      .memo-field {
        position: relative;
      }
      /* No tile feature has a text field, so the memo input copies the look of a feature. */
      .memo-input {
        box-sizing: border-box;
        width: 100%;
        height: 42px;
        padding: 0 64px 0 12px;
        border: none;
        border-radius: var(--ha-border-radius-lg, 12px);
        font: inherit;
        color: var(--primary-text-color);
        background-color: color-mix(in srgb, var(--disabled-color) 20%, transparent);
      }
      .counter {
        position: absolute;
        top: 50%;
        right: 12px;
        transform: translateY(-50%);
        font-size: var(--ha-font-size-s, 12px);
        color: var(--secondary-text-color);
      }
      .error {
        margin: 0;
      }
    `]}disconnectedCallback(){super.disconnectedCallback(),this._stoolDialog()?.close()}_stoolDialog(){return this.renderRoot.querySelector(".stool-dialog")}_openStoolDialog(t){this._stoolDialogSrc=t,this._stoolDialog()?.showModal()}_closeStoolDialog(){this._stoolDialog()?.close()}willUpdate(t){if(!t.has("visit")||!this.visit)return;if(t.get("visit")?.event_id===this.visit.event_id){this.visit.has_video&&!this._isVideoPlaying()&&this._resolveVideo(this.visit.event_id);return}this._baseline=this.visit,this._form=bt(this.visit),this._video=void 0,this._videoNote=this.visit.has_video?void 0:"camera_only",this._error=void 0,this._partialEdit=!1,this._stoolDialog()?.close(),this.visit.has_video&&this._resolveVideo(this.visit.event_id)}_isVideoPlaying(){let t=this.renderRoot.querySelector("video");return t!==null&&!t.paused}_isVideoActive(){let t=this.renderRoot.querySelector("video");return t!==null&&(!t.paused||t.currentTime>0)}async _resolveVideo(t){let n=++this._resolveSeq,s=this._video!==void 0;try{let o=await ie(this.hass,t);if(this.visit?.event_id!==t||n!==this._resolveSeq||this._isVideoActive())return;this._video=o,this._videoNote=void 0}catch(o){this.visit?.event_id===t&&n===this._resolveSeq&&!s&&(this._videoNote={error:o})}}_close(t){let n={changed:t,eventId:this.visit.event_id};this.dispatchEvent(new CustomEvent("siipet-close",{detail:n}))}_setBusy(t){this._busy=t,this.dispatchEvent(new CustomEvent("siipet-busy",{detail:{busy:t}}))}_back(){this._busy||this._close(!1)}_toggleCat(t){if(this._busy)return;let n=this._form,s=n.cats.includes(t);if(s&&n.cats.length===1)return;let o=s?n.cats.filter(r=>r!==t):[...n.cats,t];this._form={...n,cats:o}}async _save(t){this._setBusy(!0),this._error=void 0;try{await ne(this.hass,t),this._partialEdit=!1,this._close(!0)}catch(n){this._error={error:n},re(n)&&(this._partialEdit=!0)}finally{this._setBusy(!1)}}async _confirmDelete(){let t=this.l10n.text,n=window,s=await n.loadCardHelpers?.();return s?.showConfirmationDialog?s.showConfirmationDialog(this,{title:t.deleteTitle,text:t.deleteText,confirmText:t.delete,dismissText:t.cancel,destructive:!0}):n.confirm(`${t.deleteTitle}
${t.deleteText}`)}async _delete(){if(await this._confirmDelete()){this._setBusy(!0),this._error=void 0;try{await se(this.hass,this.visit.event_id),this._close(!0)}catch(t){this._error={error:t}}finally{this._setBusy(!1)}}}render(){let t=this._baseline,n=this.visit,s=this._form;if(!t||!n||!s)return l;let o=ve(t,s,{sendType:this._partialEdit}),r=o.reason==="type_required"?this.l10n.text.pickType:void 0;return a`
      ${this._renderHeader(t)}
      <div class="editor">
        ${this._renderVideo(n.cover)} ${this._renderStool(t,n.stool)}
        ${this._renderCats(s)} ${this._renderType(s)} ${this._renderMemo(s)}
        ${r?a`<div class="hint">${r}</div>`:l}
        ${this._error?a`<div class="error">${P(this._error.error,this.l10n)}</div>`:l}
        ${this._renderActions(o.data)}
      </div>
      ${n.stool?this._renderStoolDialog():l}
    `}_renderHeader(t){let n=t.cats.map(o=>o.name).join(", ")||this.l10n.text.unknown,s=[g(t.start.slice(0,10),this.l10n.locale),this.l10n.text.types[t.type],it(t.duration),...t.abnormal_reasons.slice(0,1),...t.camera?[t.camera]:[]].join(" \xB7 ");return a`
      <ha-tile-container class="header" .interactive=${!0} @action=${()=>this._back()}>
        <ha-tile-icon slot="icon" .icon=${"mdi:arrow-left"}></ha-tile-icon>
        <ha-tile-info slot="info">
          <span slot="primary">${R(t.start,this.l10n.locale)} · ${n}</span>
          <span slot="secondary">${s}</span>
        </ha-tile-info>
      </ha-tile-container>
    `}_renderType(t){let n=Ge.map(s=>({value:s,ariaLabel:this.l10n.text.types[s],icon:I(a`<ha-icon icon=${nt[s].icon}></ha-icon>`,this.l10n.text.types[s])}));return a`
      <ha-control-select
        class="type"
        .options=${n}
        .value=${t.type??void 0}
        .label=${this.l10n.text.type}
        .disabled=${this._busy}
        @value-changed=${s=>{s.stopPropagation(),!this._busy&&(this._form={...t,type:s.detail.value})}}
      ></ha-control-select>
    `}_renderMemo(t){return a`
      <div class="memo-field">
        <input
          class="memo-input"
          type="text"
          maxlength=${we}
          placeholder=${this.l10n.text.memo}
          aria-label=${this.l10n.text.memo}
          .value=${t.note}
          .disabled=${this._busy}
          @input=${n=>{this._busy||(this._form={...t,note:n.target.value})}}
        />
        <span class="counter">${t.note.length}/${we}</span>
      </div>
    `}_renderActions(t){let n=this.hass?.user?.is_admin?a`
          <ha-control-button
            class="delete"
            .label=${this.l10n.text.delete}
            .disabled=${this._busy}
            @click=${()=>this._delete()}
          >
            <span>${this.l10n.text.delete}</span>
          </ha-control-button>
        `:l;return a`
      <ha-control-button-group class="actions">
        <ha-control-button
          class="save"
          .label=${this.l10n.text.save}
          .disabled=${t===null||this._busy}
          @click=${()=>t&&this._save(t)}
        >
          <span>${this.l10n.text.save}</span>
        </ha-control-button>
        ${n}
      </ha-control-button-group>
    `}_videoNoteText(t){return t==="camera_only"?this.l10n.text.recordingOnCamera:t==="cannot_play"?this.l10n.text.cannotPlay:P(t.error,this.l10n)}_renderVideo(t){return this._videoNote!==void 0?a`<div class="video-note">${this._videoNoteText(this._videoNote)}</div>`:a`
      <video
        controls
        playsinline
        preload="none"
        poster=${t??l}
        src=${this._video??l}
        @error=${()=>{this._videoNote="cannot_play"}}
      ></video>
    `}_renderStool(t,n){let s=a`<span class="reasons">${t.abnormal_reasons.join(", ")}</span>`;return n?a`
      <div
        class="stool-row"
        role="button"
        tabindex="0"
        @click=${()=>this._openStoolDialog(n)}
        @keydown=${o=>{(o.key==="Enter"||o.key===" ")&&(o.preventDefault(),this._openStoolDialog(n))}}
      >
        <ha-icon icon="mdi:camera-outline"></ha-icon>
        <div class="stool-text">
          <div class="stool-label">${this.l10n.text.stoolPhoto}</div>
          ${s}
        </div>
        <img class="stool-photo" src=${n} alt=${this.l10n.text.stoolPhoto} />
      </div>
    `:t.abnormal_reasons.length===0?l:a`<div class="stool-row">${s}</div>`}_renderStoolDialog(){return a`
      <dialog
        class="stool-dialog"
        @click=${()=>this._closeStoolDialog()}
        @close=${()=>{this._stoolDialogSrc=void 0}}
      >
        ${this._stoolDialogSrc?a`<img
                class="stool-dialog-photo"
                src=${this._stoolDialogSrc}
                alt=${this.l10n.text.stoolPhoto}
              />`:l}
        <button class="stool-dialog-close" aria-label=${this.l10n.text.close}>
          <ha-icon icon="mdi:close"></ha-icon>
        </button>
      </dialog>
    `}_renderCats(t){return a`
      <ha-control-button-group class="cat-toggles">
        ${this.cats.map(n=>a`
            <ha-control-button
              class="cat ${t.cats.includes(n.device_id)?"on":""}"
              .label=${n.name}
              .disabled=${this._busy}
              @click=${()=>this._toggleCat(n.device_id)}
            >
              ${n.avatar?a`<img src=${n.avatar} alt="" />`:l}
              <span>${n.name}</span>
            </ha-control-button>
          `)}
      </ha-control-button-group>
    `}};customElements.get("siipet-visit-editor")||customElements.define("siipet-visit-editor",Ct);var Ke="M3.3 21.92C3.18 21.86 3.11 21.79 3.06 21.67C2.98 21.51 2.98 21.46 2.98 17.06C2.98 12.2 2.98 12.23 3.2 11.75C3.38 11.38 5.74 7.98 5.82 7.98C5.96 7.98 5.98 8.06 5.98 8.51C5.98 8.8 6 9 6.04 9.08C6.09 9.22 7.28 10.38 7.46 10.47C7.54 10.52 7.75 10.54 8.21 10.55C8.83 10.57 8.86 10.58 8.87 10.66C8.87 10.71 8.72 11.04 8.51 11.44C7.63 13.11 7.55 13.28 7.55 13.39C7.55 13.47 7.86 13.96 8.76 15.24C9.43 16.2 10.04 17.1 10.11 17.24C10.18 17.39 10.29 17.66 10.35 17.85L10.45 18.19L10.47 19.89C10.48 21.53 10.48 21.59 10.4 21.71C10.36 21.78 10.28 21.87 10.22 21.91C10.12 21.98 9.91 21.98 6.79 21.99C3.49 22 3.46 22 3.3 21.92ZM12.35 21.93C12.28 21.89 12.18 21.81 12.14 21.75C12.06 21.64 12.06 21.62 12.04 17.01L12.02 12.37L11.93 12.1C11.88 11.95 11.78 11.73 11.72 11.61C11.6 11.4 8.55 7.28 8.47 7.23C8.36 7.15 8.39 7.3 8.64 8.03C8.79 8.46 8.91 8.84 8.9 8.86C8.89 8.89 8.84 8.94 8.79 8.97C8.71 9.02 8.65 9.02 8.18 8.91C7.89 8.85 7.63 8.78 7.6 8.75C7.56 8.72 7.55 8.49 7.55 7.55C7.55 6.82 7.56 6.34 7.59 6.27C7.61 6.19 7.92 5.87 8.42 5.39C8.85 4.98 9.64 4.22 10.16 3.72C10.69 3.22 11.3 2.63 11.52 2.42C11.81 2.14 11.95 2.04 12.05 2.02C12.16 2 12.48 2.09 13.79 2.53C14.67 2.82 15.42 3.09 15.46 3.12C15.53 3.19 15.53 3.36 15.45 3.81C15.34 4.49 15.29 4.48 14.21 3.68C13.74 3.33 13.35 3.06 13.34 3.07C13.33 3.08 13.41 3.16 13.51 3.25C13.62 3.34 15.2 4.91 17.03 6.73C20.65 10.34 20.6 10.29 20.83 10.96C20.89 11.13 20.96 11.43 20.98 11.61C21.01 11.82 21.02 13.62 21.02 16.72C21.02 21.47 21.02 21.51 20.94 21.67C20.88 21.79 20.82 21.86 20.7 21.92C20.53 22 20.49 22 16.51 22C12.76 22 12.48 22 12.35 21.93Z",xt=window;xt.customIcons||(xt.customIcons={});xt.customIcons.siipet={async getIcon(i){return{path:i==="logo"?Ke:""}},async getIconList(){return[{name:"logo",keywords:["siipet","litter","cat"]}]}};var Qe=["ha-card","ha-tile-container","ha-tile-icon","ha-tile-info","ha-control-button","ha-control-button-group","ha-control-select","ha-icon"];async function Ce(i=customElements,e=window){return e.loadCardHelpers&&await e.loadCardHelpers(),Qe.filter(t=>i.get(t)===void 0)}var Ye=1800*1e3,Ze=3e3*1e3,Je=300*1e3,Xe=12,ke="siipet_visit",kt="siipet-visits-changed",At=0;function Et(){return new URLSearchParams(window.location.search).get(ke)||void 0}function ti(){let i=new URL(window.location.href);i.searchParams.delete(ke),history.replaceState(history.state,"",`${i.pathname}${i.search}${i.hash}`)}var xe=new WeakMap,ei={};function ii(i){let e=xe.get(i);return e===void 0&&(e=Object.values(i).filter(t=>t.platform==="siipet"&&t.entity_id.startsWith("event.")).map(t=>t.entity_id),xe.set(i,e)),e}function ni(i){return ii(i.entities??ei).map(e=>`${e}=${i.states[e]?.state??""}`).join("|")}var Tt=class extends f{constructor(){super();this._started=!1;this._partsLoaded=!1;this._daySeq=0;this._queueSeq=0;this._calendarSeq=new Map;this._trailing=!1;this._onVisibilityChange=()=>{document.visibilityState==="visible"&&this._due()&&this._run(()=>this._refresh())};this._onReady=()=>{this._run(()=>this._refresh())};this._onVisitsChanged=t=>{this._started&&t.detail?.source!==this&&this._run(()=>this._refresh())};this._onNavigate=()=>{this._linkEvent=void 0,this._holdingEditor=void 0,this._onLocationChange()};this._onLocationChange=()=>{this._newLink()!==void 0&&this._cats&&this._run(()=>this._followLink())};this._calendars={},this._calendarOpen=!1,this._l10n=L(void 0)}static{this.properties={hass:{attribute:!1},_config:{state:!0},_missing:{state:!0},_cats:{state:!0},_cat:{state:!0},_date:{state:!0},_month:{state:!0},_calendars:{state:!0},_first:{state:!0},_calendarOpen:{state:!0},_day:{state:!0},_queue:{state:!0},_error:{state:!0},_editing:{state:!0},_l10n:{state:!0}}}static{this.styles=st}static getConfigForm(){return{schema:[{name:"cat",selector:{device:{filter:{integration:"siipet",model:"Cat"}}}},{name:"hide_cat_picker",selector:{boolean:{}}}],computeLabel:t=>{let n=E(D());return t.name==="cat"?n.configCat:t.name==="hide_cat_picker"?n.configHideCatPicker:void 0},computeHelper:t=>{let n=E(D());return t.name==="cat"?n.configCatHelper:t.name==="hide_cat_picker"?n.configHideCatPickerHelper:void 0}}}setConfig(t){let n=E(D());if(t.cat!==void 0&&(typeof t.cat!="string"||t.cat===""))throw new Error(n.configCatInvalid);if(t.hide_cat_picker!==void 0&&typeof t.hide_cat_picker!="boolean")throw new Error(n.configHideCatPickerInvalid);let s=this._started&&(t.cat!==this._config?.cat||!!t.hide_cat_picker!=!!this._config?.hide_cat_picker);this._config=t,s&&(this._started=!1,this._cats=void 0,this._cat=void 0,this._calendars={},this._first=void 0,this._calendarOpen=!1,this._day=void 0,this._queue=void 0,this._error=void 0,this._editing=void 0,this._linkEvent=void 0,this._holdingEditor=void 0)}getCardSize(){return 8}getGridOptions(){return{columns:12,min_columns:6,rows:"auto"}}connectedCallback(){super.connectedCallback(),document.addEventListener("visibilitychange",this._onVisibilityChange),window.addEventListener("location-changed",this._onNavigate),window.addEventListener("popstate",this._onLocationChange),window.addEventListener(kt,this._onVisitsChanged),this._listen(),this._onLocationChange();let t=this._changesSeen!==void 0&&this._changesSeen!==At;this._due()||t?this._run(()=>this._refresh()):this._armTimer()}disconnectedCallback(){super.disconnectedCallback(),document.removeEventListener("visibilitychange",this._onVisibilityChange),window.removeEventListener("location-changed",this._onNavigate),window.removeEventListener("popstate",this._onLocationChange),window.removeEventListener(kt,this._onVisitsChanged),this._connection?.removeEventListener("ready",this._onReady),this._connection=void 0,this._clearTimer()}shouldUpdate(t){let n=!1;if(t.has("hass")){let r=be(this.hass);(r!==this._l10nKey||this.hass?.localize!==this._l10n.localize)&&(this._l10nKey=r,this._l10n=L(this.hass),n=!0),this._requestExceptions()}let s=!1;if(this.hass&&this._config&&(this._started||(this._started=!0,s=!0,this._run(()=>this._start())),t.has("hass"))){this._listen();let r=ni(this.hass);this._signature!==void 0&&r!==this._signature&&this._showsLatest()&&(s=!0,this._run(()=>this._refresh())),this._signature=r}let o=t.size===1&&t.has("hass");return s||n||!this.hasUpdated||!o}_requestExceptions(){let t=this.hass,n=this._l10n.locale.language;!t?.loadBackendTranslation||this._exceptionsRequested===n||(this._exceptionsRequested=n,t.loadBackendTranslation("exceptions","siipet").catch(()=>{this._exceptionsRequested===n&&(this._exceptionsRequested=void 0)}))}_run(t){return this._active?(this._trailing=!0,this._active):(this._active=this._execute(t),this._active)}async _execute(t){try{await t()}catch(n){this._error={error:n}}finally{this._active=void 0,this._trailing&&(this._trailing=!1,this._run(()=>this._refresh()))}}_lastRead(){let t=[this._catsRead,this._dataRead].filter(n=>n!==void 0);return t.length>0?Math.min(...t):void 0}_due(){let t=Date.now(),n=this._lastRead();return n!==void 0&&t-n>Ye||this._dueAt!==void 0&&t>=this._dueAt}_scheduleRenew(){this._dueAt=this._lastRead()+Ze,this._armTimer()}_scheduleRetry(t){le(t)||(this._dueAt=Date.now()+Je,this._armTimer())}_clearTimer(){this._timer!==void 0&&(clearTimeout(this._timer),this._timer=void 0)}_armTimer(){this._clearTimer(),!(!this.isConnected||this._dueAt===void 0)&&(this._timer=setTimeout(()=>{this._timer=void 0,this.isConnected&&document.visibilityState==="visible"&&this._run(()=>this._refresh())},Math.max(this._dueAt-Date.now(),0)))}_listen(){let t=this.hass?.connection;!this.isConnected||!t||t===this._connection||(this._connection?.removeEventListener("ready",this._onReady),t.addEventListener("ready",this._onReady),this._connection=t)}_refreshEditing(t){if(!this._editing)return;let n=t.find(s=>s.event_id===this._editing.event_id);n&&(this._editing=n)}_isQueue(){return this._cat!==void 0&&this._cat===this._cats?.unknown.device_id}_fixed(){return this._config?.hide_cat_picker===!0}_showsLatest(){return this._cats?this._isQueue()||this._date!==void 0&&this._date===this._cats.today:!0}_firstCat(t){return t.cats[0]?.device_id}_fallbackCat(t){return this._firstCat(t)??(t.unknown.waiting>0?t.unknown.device_id:void 0)}_catGone(t){let n=this._config?.cat;return this._fixed()&&n!==void 0&&n!==t.unknown.device_id&&!t.cats.some(s=>s.device_id===n)}_startCat(t){let n=this._config?.cat;if(n===t.unknown.device_id&&(this._fixed()||t.unknown.waiting>0))return n;if(!this._catGone(t))return t.cats.find(s=>s.device_id===n)?.device_id??this._fallbackCat(t)}async _start(){await this._loadParts()&&(await this._readCatsAndInit(),await this._followLink())}async _loadParts(){if(this._partsLoaded)return!0;let t;try{t=await Ce()}catch(n){return this._error={error:n},!1}return t.length>0?(this._missing=t,!1):(this._partsLoaded=!0,!0)}async _readCatsAndInit(){let t=await this._readCats();t&&await this._init(t)}async _init(t){this._date=t.today,this._month=v(t.today),this._cat=this._startCat(t),await this._loadSelection()}async _readCats(){this._changesSeen=At;try{return this._cats=await Zt(this.hass),this._catsRead=Date.now(),this._cats}catch(t){this._error={error:t},this._scheduleRetry(t);return}}async _loadSelection(){if(!(this._cat===void 0||this._date===void 0)){if(this._isQueue()){await this._loadQueue();return}await Promise.all([this._loadDay(),this._loadCalendar(v(this._date))])}}async _loadDay(){let t=this._cat,n=this._date,s=++this._daySeq,o=()=>s===this._daySeq&&t===this._cat&&n===this._date;try{let r=await Jt(this.hass,n,t);o()&&(this._day=r,this._dataRead=Date.now(),this._scheduleRenew(),this._refreshEditing(r.visits))}catch(r){o()&&(this._error={error:r},this._scheduleRetry(r))}}async _loadQueue(){let t=this._cat,n=++this._queueSeq,s=()=>n===this._queueSeq&&t===this._cat;try{let o=await Xt(this.hass);if(!s())return;if(this._dataRead=Date.now(),this._scheduleRenew(),this._cats&&(this._cats={...this._cats,unknown:{...this._cats.unknown,waiting:o.visits.length}}),o.visits.length===0&&!this._fixed()){let r=this._cats&&this._firstCat(this._cats);if(r!==void 0){this._selectCat(r);return}}this._queue=o,this._refreshEditing(o.visits)}catch(o){s()&&(this._error={error:o},this._scheduleRetry(o))}}async _loadCalendar(t){let n=this._cat,s=(this._calendarSeq.get(t)??0)+1;this._calendarSeq.set(t,s);let o=()=>s===this._calendarSeq.get(t)&&n===this._cat;try{let r=await ee(this.hass,t,n);o()&&(this._calendars={...this._calendars,[t]:r},this._first=r.first)}catch(r){o()&&(this._error={error:r})}}async _refresh(){await this._readAgain(),await this._followLink()}async _readAgain(){if(this._error=void 0,this._dueAt=void 0,this._clearTimer(),this._missing?.length)return;if(!this._cats){await this._loadParts()&&await this._readCatsAndInit();return}let t=this._date,n=t===this._cats.today,s=await this._readCats();if(s){if(n&&this._date===t&&t!==s.today&&(this._date=s.today,this._month=v(s.today)),this._cat===void 0){await this._init(s);return}if(this._isQueue()&&s.unknown.waiting===0&&!this._fixed()){let o=this._firstCat(s);if(o!==void 0){this._selectCat(o);return}}await this._loadSelection()}}_newLink(){let t=Et();return t===void 0&&(this._linkEvent=void 0),t!==this._linkEvent?t:void 0}_editorElement(){return this.renderRoot.querySelector("siipet-visit-editor")}_onEditorBusy(t){t.detail.busy?this._busyEditor=t.target??void 0:this._busyEditor===t.target&&(this._busyEditor=void 0)}_linkWaits(){let t=this._editing?this._editorElement():null;return t===null?!1:t===this._busyEditor?(this._holdingEditor=t,!0):t===this._holdingEditor}async _followLink(){let t=this._newLink();if(t===void 0||!this._cats||this._linkWaits()||this._fixed()&&this._cat===void 0)return;this._linkEvent=t;let n;try{n=await te(this.hass,t)}catch(o){this._linkFailed(t,o);return}if(!this.isConnected){this._linkEvent=void 0;return}if(!this._cats||Et()!==t)return;if(this._linkWaits()){this._linkEvent=void 0;return}let s=this._linkedCat(this._cats,n.visit);s!==void 0&&(ti(),this._linkEvent=void 0,this._openLinked(s,n))}_linkFailed(t,n){(!this.isConnected||!ae(n))&&(this._linkEvent=void 0),Et()===t&&(this._error={error:n})}_linkedCat(t,n){let s=n.cats.length>0?n.cats.flatMap(o=>o.device_id!==null?[o.device_id]:[]):[t.unknown.device_id];return this._cat!==void 0&&s.includes(this._cat)?this._cat:this._fixed()?void 0:s[0]}_openLinked(t,{date:n,visit:s}){let o=t===this._cats?.unknown.device_id;t!==this._cat?(o||(this._date=n,this._month=v(n)),this._selectCat(t)):!o&&n!==this._date&&this._goToDay(n),this._editing=s}_selectCat(t){t!==this._cat&&(this._cat=t,this._calendars={},this._first=void 0,this._calendarOpen=!1,this._day=void 0,this._queue=void 0,this._error=void 0,this._loadSelection())}_goToDay(t){this._date=t,this._month=v(t),this._calendarOpen=!1,this._day=void 0,this._error=void 0,this._loadDay(),this._month in this._calendars||this._loadCalendar(this._month)}_shiftMonth(t){this._month=vt(this._month,t),this._error=void 0,this._loadCalendar(this._month)}async _closeEditor(t){let{changed:n,eventId:s}=t.detail,o=t.target===this._editorElement()&&this._editing?.event_id===s;if(o&&(this._editing=void 0,this._holdingEditor=void 0),n){At+=1;let h={source:this};window.dispatchEvent(new CustomEvent(kt,{detail:h})),await this._run(()=>this._refresh())}else o&&this._onLocationChange();if(!o)return;await this.updateComplete,[...this.shadowRoot?.querySelectorAll(".visit")??[]].find(h=>h.dataset.event===s)?.scrollIntoView({block:"nearest"})}_toggleCalendar(){this._month=v(this._date),this._calendarOpen=!this._calendarOpen}render(){if(this._missing?.length)return a`
        <ha-card>
          <div class="message alone missing">
            ${this._l10n.text.missingParts(this._missing.join(", "))}
          </div>
        </ha-card>
      `;let t=this._cats,n=this._cat,s=t!==void 0&&n!==void 0;return a`
      <ha-card style="--tile-color: var(--state-icon-color)">
        ${t&&!t.available?this._renderNotice(t):l}
        ${t&&n===void 0?this._renderNoCat(t):l}
        ${t&&n!==void 0?this._renderMain(t,n):l}
        ${!s&&this._error?a`<div class="error">${P(this._error.error,this._l10n)}</div>`:l}
      </ha-card>
    `}_renderNoCat(t){let n=this._catGone(t)?this._l10n.text.catGone:this._l10n.text.noCats;return a`<div class="message alone">${n}</div>`}_renderNotice(t){let n=g(t.updated_at.slice(0,10),this._l10n.locale);return a`
      <div class="notice">
        ${this._l10n.text.notUpdating(`${n} ${R(t.updated_at,this._l10n.locale)}`)}
      </div>
    `}_renderMain(t,n){return this._editing?a`${Yt(this._editing.event_id,a`
          <siipet-visit-editor
            .hass=${this.hass}
            .visit=${this._editing}
            .cats=${t.cats}
            .l10n=${this._l10n}
            @siipet-busy=${s=>this._onEditorBusy(s)}
            @siipet-close=${s=>this._closeEditor(s)}
          ></siipet-visit-editor>
        `)}`:a`
      ${this._renderView(t,n)}
      ${this._error?a`<div class="error">${P(this._error.error,this._l10n)}</div>`:l}
      ${this._renderVisits()}
    `}_renderView(t,n){let s=ge(t,n,this._fixed(),_=>this._selectCat(_),this._l10n);if(this._isQueue())return yt({icon:"mdi:help",primary:this._l10n.text.unknown,secondary:_e(this._queue?.visits.length??t.unknown.waiting,this._l10n),features:a`${s}`});let o=t.cats.find(_=>_.device_id===n),r=this._date,h=this._month??v(r),d=this._first,u=v(t.today),p=me({date:r,canGoBack:d===void 0||gt(r,-1)>=d,canGoForward:r<t.today,marked:this._calendars[v(r)]?.days[r]?.marked??!1,l10n:this._l10n,onShift:_=>this._goToDay(gt(r,_)),onToggle:()=>this._toggleCalendar()}),c=this._calendarOpen?fe({month:h,calendar:this._calendars[h],selected:r,canGoBack:h>vt(u,-Xe),canGoForward:h<u,l10n:this._l10n,onShiftMonth:_=>this._shiftMonth(_),onOpenDay:_=>this._goToDay(_)}):l;return yt({imageUrl:o?.avatar??void 0,icon:o?.avatar?void 0:"mdi:cat",primary:o?.name??"",secondary:this._day?pe(r,this._day.summary,this._l10n):g(r,this._l10n.locale),features:a`${p} ${c} ${s}`})}_renderVisits(){let t=n=>{this._editing=n};return this._isQueue()?$t(this._queue?.visits,!0,t,this._l10n):$t(this._day?.visits,!1,t,this._l10n)}};customElements.get("siipet-visits-card")||customElements.define("siipet-visits-card",Tt);var ot=window;ot.customCards=ot.customCards??[];ot.customCards.some(i=>i.type==="siipet-visits-card")||ot.customCards.push({type:"siipet-visits-card",get name(){return E(D()).pickerName},get description(){return E(D()).pickerDescription},preview:!0});export{Tt as SiiPetVisitsCard};
