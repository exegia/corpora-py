<?xml version='1.0' encoding='utf-8'?>
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron" xmlns="http://www.tei-c.org/ns/1.0" xmlns:rng="http://relaxng.org/ns/structure/1.0" queryBinding="xslt"><sch:ns prefix="tei" uri="http://www.tei-c.org/ns/1.0"/><sch:ns prefix="xml" uri="http://www.w3.org/XML/1998/namespace"/>
    <sch:ns prefix="t" uri="http://www.tei-c.org/ns/1.0"/><sch:pattern id="logical">
     <sch:rule context="t:TEI"><sch:assert test="@xml:id and @xml:lang and count(t:text)=1">Standalone TEI requires ID, language and one text.</sch:assert><sch:assert test="t:teiHeader/t:fileDesc/t:editionStmt/t:edition">Edition must be declared.</sch:assert></sch:rule>
     <sch:rule context="t:text//*"><sch:assert test="@xml:id">Every reading node needs a stable ID.</sch:assert><sch:assert test="not(self::t:pb or self::t:lb or self::t:fw or self::t:cb)">Page boundaries, running matter and print wrapping are forbidden.</sch:assert><sch:assert test="not(@style or @facs or @rendition)">CSS/layout must stay in external provenance.</sch:assert><sch:assert test="not(@*[not(namespace-uri()='http://www.w3.org/XML/1998/namespace' and (local-name()='id' or local-name()='lang')) and not(namespace-uri()='' and ((local-name()='n' and local-name(..)='div') or (local-name()='type' and (local-name(..)='div' or local-name(..)='list' or local-name(..)='ref')) or (local-name()='rend' and local-name(..)='hi') or (local-name()='target' and local-name(..)='ref') or (local-name()='url' and local-name(..)='graphic') or ((local-name()='role' or local-name()='rows' or local-name()='cols') and (local-name(..)='cell' or local-name(..)='row')) or (local-name()='reason' and (local-name(..)='gap' or local-name(..)='unclear'))))])">Only profile-declared instance attributes are allowed.</sch:assert></sch:rule>
     <sch:rule context="t:body|t:front|t:back|t:div|t:lg|t:list|t:table|t:row"><sch:assert test="not(text()[normalize-space(.)])">Structural containers cannot hide unclassified text.</sch:assert></sch:rule>
     <sch:rule context="t:span"><sch:assert test="@xml:id and @n and starts-with(@from,'#') and starts-with(@to,'#') and not(@target)">Canonical span requires local anchor endpoints, ID and source number.</sch:assert><sch:assert test="count(//t:anchor[@xml:id=substring(current()/@from,2)])=1 and count(//t:anchor[@xml:id=substring(current()/@to,2)])=1">Endpoints must exist once.</sch:assert></sch:rule>
     <sch:rule context="t:cell"><sch:assert test="not(@rows) or (number(@rows)&gt;0 and floor(number(@rows))=number(@rows))">Positive integer rowspan.</sch:assert><sch:assert test="not(@cols) or (number(@cols)&gt;0 and floor(number(@cols))=number(@cols))">Positive integer colspan.</sch:assert></sch:rule>
     <sch:rule context="t:gap|t:unclear"><sch:assert test="@reason">Uncertainty requires source-evidenced reason.</sch:assert></sch:rule>
     <sch:rule context="t:choice"><sch:assert test="not(text()[normalize-space(.)]) and not(*[normalize-space(following-sibling::text())])">Choice alternatives cannot hide reading text or tails.</sch:assert></sch:rule>
     <sch:rule context="t:expan"><sch:assert test="parent::t:choice">Expansion text requires an explicit abbreviation alternative.</sch:assert></sch:rule>
    </sch:pattern>
   <sch:pattern id="corpora-tei-att.cmc-generatedBy-CMC_generatedBy_within_post-constraint-rule-1">
      <sch:rule xmlns:xi="http://www.w3.org/2001/XInclude" context="tei:*[@generatedBy]">
         <sch:assert test="ancestor-or-self::tei:post">The @generatedBy attribute is for use within a &lt;post&gt; element.</sch:assert>
      </sch:rule>
   </sch:pattern>
   <sch:pattern id="corpora-tei-att.datable.w3c-att-datable-w3c-when-constraint-rule-2">
      <sch:rule xmlns:xi="http://www.w3.org/2001/XInclude" context="tei:*[@when]">
         <sch:report test="@notBefore|@notAfter|@from|@to" role="nonfatal">The @when attribute cannot be used with any other att.datable.w3c attributes.</sch:report>
      </sch:rule>
   </sch:pattern>
   <sch:pattern id="corpora-tei-att.datable.w3c-att-datable-w3c-from-constraint-rule-3">
      <sch:rule xmlns:xi="http://www.w3.org/2001/XInclude" context="tei:*[@from]">
         <sch:report test="@notBefore" role="nonfatal">The @from and @notBefore attributes cannot be used together.</sch:report>
      </sch:rule>
   </sch:pattern>
   <sch:pattern id="corpora-tei-att.datable.w3c-att-datable-w3c-to-constraint-rule-4">
      <sch:rule xmlns:xi="http://www.w3.org/2001/XInclude" context="tei:*[@to]">
         <sch:report test="@notAfter" role="nonfatal">The @to and @notAfter attributes cannot be used together.</sch:report>
      </sch:rule>
   </sch:pattern>
   <sch:pattern id="corpora-tei-att.pointing-targetLang-targetLang-constraint-rule-6">
      <sch:rule xmlns:xi="http://www.w3.org/2001/XInclude" context="tei:*[not(self::tei:schemaSpec)][@targetLang]">
         <sch:assert test="@target">@targetLang should only be used on &lt;<sch:name/>&gt; if @target is specified.</sch:assert>
      </sch:rule>
   </sch:pattern>
   <sch:pattern id="corpora-tei-att.typed-subtypeTyped-constraint-rule-7">
      <sch:rule xmlns:xi="http://www.w3.org/2001/XInclude" context="tei:*[@subtype]">
         <sch:assert test="@type">
          The &lt;<sch:name/>&gt; element should not be categorized in detail with @subtype unless also categorized in general with @type.
        </sch:assert>
      </sch:rule>
   </sch:pattern>
   <sch:pattern id="corpora-tei-p-abstractModel-structure-p-in-ab-or-p-constraint-rule-8">
            <sch:rule context="tei:p">
               <sch:report test="(ancestor::tei:ab or ancestor::tei:p) and                        not( ancestor::tei:floatingText                           | parent::tei:exemplum                           | parent::tei:item                           | parent::tei:note                           | parent::tei:q                           | parent::tei:quote                           | parent::tei:remarks                           | parent::tei:said                           | parent::tei:sp                           | parent::tei:stage                           | parent::tei:cell                           | parent::tei:figure )">
          Abstract model violation: Paragraphs may not occur inside other paragraphs or &lt;ab&gt; elements.
        </sch:report>
            </sch:rule>
         </sch:pattern>
         <sch:pattern id="corpora-tei-p-abstractModel-structure-p-in-l-constraint-rule-9">
            <sch:rule context="tei:l//tei:p">
               <sch:assert test="ancestor::tei:floatingText | parent::tei:figure | parent::tei:note">
          Abstract model violation: Metrical lines (&lt;l&gt; elements) may not contain higher-level structural elements such as &lt;div&gt;, &lt;p&gt;, or &lt;ab&gt;, unless &lt;p&gt; is a child of &lt;figure&gt; or &lt;note&gt;, or is a descendant of &lt;floatingText&gt;.
        </sch:assert>
            </sch:rule>
         </sch:pattern>
         <sch:pattern id="corpora-tei-ref-refAtts-constraint-rule-10">
            <sch:rule context="tei:ref">
               <sch:report test="@target and @cRef">Only one of the attributes @target and @cRef may be supplied on &lt;<sch:name/>&gt;.</sch:report>
            </sch:rule>
         </sch:pattern>
         <sch:pattern id="corpora-tei-list-gloss-list-must-have-labels-constraint-rule-11">
            <sch:rule context="tei:list[@type='gloss']">
               <sch:assert test="tei:label">
          The content of a "gloss" list should include a sequence of
          one or more pairs of a &lt;label&gt; element followed by an
          &lt;item&gt; element.
        </sch:assert>
            </sch:rule>
         </sch:pattern>
         <sch:pattern id="corpora-tei-l-abstractModel-structure-l-in-l-constraint-rule-12">
            <sch:rule context="tei:l">
               <sch:report test="ancestor::tei:l[not(.//tei:note//tei:l[. = current()])]">Abstract model violation: Metrical lines (&lt;l&gt; elements) may not contain &lt;l&gt; or &lt;lg&gt; elements.</sch:report>
            </sch:rule>
         </sch:pattern>
         <sch:pattern id="corpora-tei-lg-atleast1oflggapl-constraint-rule-13">
            <sch:rule context="tei:lg">
               <sch:assert test="count(descendant::tei:lg|descendant::tei:l|descendant::tei:gap) &gt; 0">An &lt;lg&gt; element must contain at least one child &lt;l&gt;, &lt;lg&gt;, or &lt;gap&gt; element.</sch:assert>
            </sch:rule>
         </sch:pattern>
         <sch:pattern id="corpora-tei-lg-abstractModel-structure-lg-in-l-constraint-rule-14">
            <sch:rule context="tei:lg">
               <sch:report test="ancestor::tei:l[not(.//tei:note//tei:lg[. = current()])]">Abstract model violation: Lines may not contain line groups.</sch:report>
            </sch:rule>
         </sch:pattern>
         <sch:pattern id="corpora-tei-div-abstractModel-structure-div-in-l-constraint-rule-15">
            <sch:rule context="tei:l//tei:div">
               <sch:assert test="ancestor::tei:floatingText">
          Abstract model violation: Metrical lines (&lt;l&gt; elements) may not contain higher-level structural elements such as &lt;div&gt;, unless &lt;div&gt; is a descendant of &lt;floatingText&gt;.
        </sch:assert>
            </sch:rule>
         </sch:pattern>
         <sch:pattern id="corpora-tei-div-abstractModel-structure-div-in-ab-or-p-constraint-rule-16">
            <sch:rule context="tei:div">
               <sch:report test="(ancestor::tei:p or ancestor::tei:ab) and not(ancestor::tei:floatingText)">
          Abstract model violation: &lt;p&gt; and &lt;ab&gt; may not contain higher-level structural elements such as &lt;div&gt;, unless &lt;div&gt; is a descendant of &lt;floatingText&gt;.
        </sch:report>
            </sch:rule>
         </sch:pattern>
         <sch:pattern id="corpora-tei-span-target-from-constraint-rule-17">
            <sch:rule context="tei:span">
               <sch:report test="@from and @target">
          Only one of the attributes @target and @from may be supplied on &lt;<sch:name/>&gt;.
        </sch:report>
            </sch:rule>
         </sch:pattern>
         <sch:pattern id="corpora-tei-span-targetto-constraint-rule-18">
            <sch:rule context="tei:span">
               <sch:report test="@to and @target">
          Only one of the attributes @target and @to may be supplied on &lt;<sch:name/>&gt;.
        </sch:report>
            </sch:rule>
         </sch:pattern>
         <sch:pattern id="corpora-tei-span-tonotfrom-constraint-rule-19">
            <sch:rule context="tei:span">
               <sch:report test="@to and not(@from)">
          If @to is supplied on &lt;<sch:name/>&gt;, @from must be supplied as well.
        </sch:report>
            </sch:rule>
         </sch:pattern>
         <sch:pattern id="corpora-tei-span-tofrom-constraint-rule-20">
            <sch:rule context="tei:span">
               <sch:report test="contains(normalize-space(@to),' ') or contains(normalize-space(@from),' ')">
          The attributes @to and @from on &lt;<sch:name/>&gt; may each contain only a single value.
        </sch:report>
            </sch:rule>
         </sch:pattern>
         </sch:schema>
  