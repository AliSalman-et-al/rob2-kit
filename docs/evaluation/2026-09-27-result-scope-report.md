# Trial-specific rob2-kit benchmark

This report measures agreement with the frozen provisional catalog labels. It is not an adjudicated estimate of scientific accuracy.

- Model: `gpt-6-luna` with `medium` reasoning.
- Manifest rows: 26 abstract-eligible outcome/trial cases.
- Finalized scored cases: 25 (125 domain cells).
- Cases excluded from scoring: 1.
- Combined primary score: 25 cases (125 domain cells).
- Result-scope denominators: mechanical matches 0; mechanical mismatches 26; adjudicated equivalents 25; accepted scope differences 0; unavailable 0; unadjudicated mismatches 0; unresolved 1.
- The mechanical mismatch count includes cases later accepted as equivalent or held for review.
- Recorded Proposal relations: exact 15; broader 0; narrower 11; component 0; related 0; unknown 0 (manifest denominator 26).
- Cases held for separate review: 1; they remain in manifest coverage and are excluded from the combined primary score.
- Exact scoring compares Low, Some Concerns, and High. Binary scoring maps Some Concerns and High to Non-Low.
- The frozen catalog contains no reference High labels, so High sensitivity is not estimable from this cohort.

## Result-scope correspondence

Mechanical comparison, recorded Proposal relation, reviewer adjudication, and scoring eligibility are separate report fields. Proposal relation compares the requested target with the reported Result; it does not establish correspondence to the frozen expected Result. An adjudication decision is the recorded reviewer claim; scorer identity checks do not validate its scientific meaning.

- **Adverse Events / ARASENS**
  - Proposal relation: `narrower`
  - Result status: `unresolved`
  - Differing facets: `comparison[0].id`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `reported_scope.analysis_population`, `reported_scope.endpoint.definition`, `reported_scope.endpoint.name`, `reported_scope.group_values[0].group_id`, `reported_scope.group_values[0].statistic`, `reported_scope.group_values[0].unit`, `reported_scope.group_values[0].value`, `reported_scope.group_values[1].group_id`, `reported_scope.group_values[1].statistic`, `reported_scope.group_values[1].unit`, `reported_scope.group_values[1].value`
  - Adjudication identity: `expected_result_sha256=983c51392a5fdba287fb785bf03d9b13b08ef60a7e3a1432c0ad654efc0ffe32; review_identity=sha256:715ec2c0c86977ad9df708c8506a829792df0f1b67ab1095fd209bc79f4dfce1; result_identity=sha256:28622307e5a94f9c3ee01bc782acf3a29164495e1769aa04f8ea3fe656c160b8`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: ARASENS main_article.pdf, pp. 3, 4, 8
  - Review required: The approved safety Result uses treatment-received group membership, including a participant assigned to placebo who received darolutamide. The existing generic equivalence rationale does not address this grouping facet; obtain a separate source-grounded decision before including this case in the primary score.

- **Adverse Events / ARCHES**
  - Proposal relation: `narrower`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `reported_scope.analysis_population`, `reported_scope.endpoint.definition`, `reported_scope.endpoint.name`, `reported_scope.group_values[0].group_id`, `reported_scope.group_values[0].statistic`, `reported_scope.group_values[0].unit`, `reported_scope.group_values[0].value`, `reported_scope.group_values[1].group_id`, `reported_scope.group_values[1].statistic`, `reported_scope.group_values[1].unit`, `reported_scope.group_values[1].value`
  - Adjudication identity: `expected_result_sha256=844f01008b7db0111cb36bae8d3c592125b6000b9718710c079e8298f31137f0; review_identity=sha256:3a1af0596040884536d0abf2b24380bc640fbbc4efe4b6240d99aa06a5922bdc; result_identity=sha256:eebb8afe8a9de9395e1abafc11552e7d61dfe537d5c1372819aeb5d5b0b941b4`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: ARCHES main_article.pdf, pp. 2, 10

- **Adverse Events / ENZAMET**
  - Proposal relation: `narrower`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `reported_scope.analysis_population`, `reported_scope.endpoint.definition`, `reported_scope.endpoint.name`, `reported_scope.group_values[0].group_id`, `reported_scope.group_values[0].statistic`, `reported_scope.group_values[0].value`, `reported_scope.group_values[1].group_id`, `reported_scope.group_values[1].statistic`, `reported_scope.group_values[1].value`
  - Adjudication identity: `expected_result_sha256=65cca14d9a2db91df95d4c4c803e588a08fd6b15758bec9cb9033c0544ec132e; review_identity=sha256:0667da5bbdb358a0ff50f9f1ffbeb041289314e1934955ba6500c4562c17c00e; result_identity=sha256:85c7cae027ca9535d066d84c32d2be17a2db88d50895c52d1d276228c2531114`
  - Decision: `equivalent`
  - Rationale: The requested endpoint is Grade 3 adverse events under NCI-CTCAE version 4.0.2. The proposal target states that definition and its reported safety-population Grade 3 row is 277/563 (49%) versus 194/558 (35%), matching the frozen result. “Any adverse event” is the table heading; the selected category is the Grade 3 row.
  - Source locator: ENZAMET main_article.pdf, pp. 2, 3, 9

- **Adverse Events / LATITUDE**
  - Proposal relation: `narrower`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `reported_scope.analysis_population`, `reported_scope.endpoint.definition`, `reported_scope.endpoint.name`, `reported_scope.group_values[0].group_id`, `reported_scope.group_values[0].statistic`, `reported_scope.group_values[0].unit`, `reported_scope.group_values[0].value`, `reported_scope.group_values[1].group_id`, `reported_scope.group_values[1].statistic`, `reported_scope.group_values[1].unit`, `reported_scope.group_values[1].value`
  - Adjudication identity: `expected_result_sha256=2fd5257b0a7c6574c568fda38110c75e9aae8d46bae15ed310ae498e45d75e87; review_identity=sha256:02bd452fe5d76f1e82a7cb4a50e7fb0325a1e4b9ff1e872f9f8cd38ed730a965; result_identity=sha256:81090da1ee861352cb232e65340861c265befb80013e16b7593905d62f50991a`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial result and estimate supplied in the prompt. The source describes the endpoint scope or measurement differently from the frozen wording; the cited main-article passages identify the same comparison, analysis, and reported estimate. The scope relation remains recorded for the RoB 2 assessment.
  - Source locator: LATITUDE main_article.pdf, pp. 3, 4, 8

- **Adverse Events / PEACE-1**
  - Proposal relation: `narrower`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `reported_scope.analysis_population`, `reported_scope.endpoint.definition`, `reported_scope.endpoint.name`, `reported_scope.group_values[0].group_id`, `reported_scope.group_values[0].statistic`, `reported_scope.group_values[0].unit`, `reported_scope.group_values[0].value`, `reported_scope.group_values[1].group_id`, `reported_scope.group_values[1].statistic`, `reported_scope.group_values[1].unit`, `reported_scope.group_values[1].value`
  - Adjudication identity: `expected_result_sha256=bd9716cc0a31ce9b4e94532d8f3b8d36e517ccd4f1af0882d1c9b5e0dd96c861; review_identity=sha256:e4de8a800f75fcbbf8ddb67c903cb9c0247769e82731c0cc446e153f5478446f; result_identity=sha256:dc69459b3b9dd18c43e48060f1f94118f6edee7fb8e0e5af080270b270af9c79`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: PEACE-1 main_article.pdf, pp. 3, 4, 11

- **Adverse Events / STAMPEDE**
  - Proposal relation: `narrower`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `reported_scope.analysis_population`, `reported_scope.endpoint.definition`, `reported_scope.endpoint.name`, `reported_scope.group_values[0].group_id`, `reported_scope.group_values[0].statistic`, `reported_scope.group_values[0].unit`, `reported_scope.group_values[0].value`, `reported_scope.group_values[1].group_id`, `reported_scope.group_values[1].statistic`, `reported_scope.group_values[1].unit`, `reported_scope.group_values[1].value`
  - Adjudication identity: `expected_result_sha256=e722bcde3716f8c3b3baf80048439710c65d6cc151ecef10453c73be88c0cda2; review_identity=sha256:2dd1dd4677b18c40e90a23c00b65c279f7e65a143a8b1e4b13ba10ddd8dca5dc; result_identity=sha256:acb22ff6863d490dcf1835936441e2a1c5575a618abc239d00f6c6932ebb5bd5`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: STAMPEDE main_article.pdf, pp. 1, 6, 10

- **Adverse Events / TITAN**
  - Proposal relation: `narrower`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].id`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `reported_scope.analysis_population`, `reported_scope.endpoint.definition`, `reported_scope.endpoint.name`, `reported_scope.group_values[0].group_id`, `reported_scope.group_values[0].statistic`, `reported_scope.group_values[0].unit`, `reported_scope.group_values[0].value`, `reported_scope.group_values[1].group_id`, `reported_scope.group_values[1].statistic`, `reported_scope.group_values[1].unit`, `reported_scope.group_values[1].value`
  - Adjudication identity: `expected_result_sha256=3acdf67ea7c4481b4e8238afa2fb543c9ec81415b9d4a63fb820e1d1423b03b1; review_identity=sha256:6f97b4e7080188c2fef00ac81a5d3d4101272efcca4bb681c0b9e8ad2965eb9b; result_identity=sha256:7fe09c97c70fcd1d13d11b85c07d281f874411acc7edd9146ef6cee7c5a71a18`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: TITAN main_article.pdf, pp. 2, 3, 10

- **Overall Survival / ARASENS**
  - Proposal relation: `narrower`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].id`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=536cfcc52952e313b6e3c7d5c02c43a00c79793dcb4fbf729ef32191d92070eb; review_identity=sha256:dd3d3125a44b7dddb5b8458eeedecc345db533fa34d055348c8f3bc97f7bcfef; result_identity=sha256:0cd2e673d84bfb8d54b4fa07c136515137384c57e5792307fa3c1e118eed8878`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: ARASENS main_article.pdf, pp. 3, 4

- **Overall Survival / ARCHES**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.endpoint.name`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=56f2550fbacc7d7534b0765e8eb3605ed38438886316800202bd4d1942e779b4; review_identity=sha256:2664c5280f875a5c40af47ec3b2bc4f1915dcdf9fc21383acbb11ea094b902d8; result_identity=sha256:dbe530ee7803f2c458013b30e6c522be6d6116bbdb8452c44082c6b2f7cfcf64`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: ARCHES main_article.pdf, pp. 2, 3, 7

- **Overall Survival / CHAARTED**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=e48908ca91bb3e2689daa4f303981c65cb26b8bcc55da7d3404df5d0301bd168; review_identity=sha256:f71acf1d6db590e69969b9aecf87eda994bdaf519aa0f41b69f07f09ca5fee9a; result_identity=sha256:63e698f0288e16ec991b8fdeb7063a77b68bee3ffbb1db758600676ef8c92213`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: CHAARTED main_article.pdf, pp. 2, 3, 4, 6

- **Overall Survival / ENZAMET**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=be0fe5f1296118f64fe41da0614a3936cad1d45c9c17f1416e62fd859aef5ae7; review_identity=sha256:9cd5a5056cee4562dcc2cf92f3e4553423e7e5ae1ab4cb25944da049bd5ccd9f; result_identity=sha256:2fa48ffad7541057e652dc682bd24f5ff4b7141587f403634afcc9842b1a99f5`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: ENZAMET main_article.pdf, pp. 3, 5

- **Overall Survival / GETUG-AFU-15**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `estimate`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.endpoint.name`, `reported_scope.estimate`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=4544b7416346eba4a2f0e9443a929c55549109996f64ccec428d395710635d45; review_identity=sha256:cb36c967fe5993e004e6a9ab135e4182450889f28c69b41282c9a14e6cf899f3; result_identity=sha256:6c6088a5b1c88859161ee72e7a59ea04f8dbeabd9a90c1231280b02c01c27d8c`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: GETUG-AFU-15 main_article.pdf, pp. 1, 2, 3, 4

- **Overall Survival / LATITUDE**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].id`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=fcfba3ff5675b9e595f61ec94b79eec5a09d48b6bf7ccb09bd02f0f0a8d1fe99; review_identity=sha256:cb7eeb593e8f8d051bcb2543a7b54a066e293da61ec16b95fe8b4dfc85b45ffb; result_identity=sha256:25a6d3a1335ffa3e1f422e2311d3f0470ae6f110b053a630f45a93b2085ae536`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: LATITUDE main_article.pdf, pp. 1, 3, 4

- **Overall Survival / PEACE-1**
  - Proposal relation: `narrower`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `estimate`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.endpoint.name`, `reported_scope.estimate`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=e96690701f6252b1a25ac24091c5fdb537ade46fb1177801ce1f0add3ddabd54; review_identity=sha256:9e5c724454d73ccaa94d6dcbceaf863069951afc688fce8378392c4fa58b76a1; result_identity=sha256:7d04dc2fae75ada93202abf40f49e3112092792aec90f846663f209bd1392364`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: PEACE-1 main_article.pdf, pp. 1, 3, 5, 6, 9

- **Overall Survival / STAMPEDE**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=c9b94a864d2cf8ab17d2db4119811acf25e9d41600f82648c1f403fa4cd7de37; review_identity=sha256:1c88bf7a4ca4033cb9f605a7d7cabbabc296045aaf50853b201ed6618b2a1307; result_identity=sha256:721d4be0e60f09ae13811e24f0e32d643b78a6fe80b8bea2a0527c3461db6512`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: STAMPEDE main_article.pdf, pp. 1, 2, 3, 4

- **Overall Survival / SWOG-1216**
  - Proposal relation: `narrower`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=b43130c8eb8ca76c0709d67cedadfd0960d4058ddfdd1709d6d4383410aed0d8; review_identity=sha256:e0593acb34943d89d6ab1cfc8a73a679ec8027742ae30888c037ca3bafcc4308; result_identity=sha256:635965b7b41783bb4723d0e9fda31f169393bdf0e2e8469847acfdd1754cbe0c`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: SWOG-1216 main_article.pdf, pp. 2, 3, 4

- **Overall Survival / TITAN**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].id`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=2df3aea252a3871dca93f3d61d7110fa7ec60b9c7a1967e5da64baf812f7c500; review_identity=sha256:1f048192d719a97d6990fe0a7fbe6fc5d09f2dacf3a441fca3392c810a28fb28; result_identity=sha256:6caab9da6eae7e8dc10aead1fbfd67020fd3334e373ed1add233645dd2f30162`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: TITAN main_article.pdf, pp. 2, 3, 4, 7

- **Progression-Free Survival / ARCHES**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.endpoint.name`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=64c5ac33eb741226ba02a50603217d6f2a26acebcb8f5961927d6dfc6c2f4780; review_identity=sha256:282e672d44854180b0931ea4fa891884cc44a582941c5aba2c746f4d822c0aa2; result_identity=sha256:28c038cb703285b742f4c896e586596340659fd57253b38ab78f9bba7370eeba`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial result and estimate supplied in the prompt. The source describes the endpoint scope or measurement differently from the frozen wording; the cited main-article passages identify the same comparison, analysis, and reported estimate. The scope relation remains recorded for the RoB 2 assessment.
  - Source locator: ARCHES main_article.pdf, pp. 2, 3, 7

- **Progression-Free Survival / CHAARTED**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.endpoint.name`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=75b54c8f2aba7bf6b60aa34df599643b8ee5fc370ba9a0952dad9fb1d8a0fbf5; review_identity=sha256:823a1b62dfbe4ebd014f3c49e5bd25e4ac85438b5d73d008938d866305fe1b18; result_identity=sha256:b4fc03f068a0f99f83595aece509a7306808ca16e79802ad7f4a26cf0975cca5`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: CHAARTED main_article.pdf, pp. 3, 4, 7, 8

- **Progression-Free Survival / ENZAMET**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].id`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=8a28cf3532d0335cf66f76230d9e2fd09c4e7ad1372591cfba76110bff566186; review_identity=sha256:76550ccfaa239b1c5f7f7bf79e7524d6cf1ac3f3c08dd9398942dc651597178b; result_identity=sha256:9ca7f44510c810b8cc8b5651bb08401e89bccd16840010fd9b116ee625e5741e`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: ENZAMET main_article.pdf, pp. 2, 3, 5, 6

- **Progression-Free Survival / GETUG-AFU-15**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.endpoint.name`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=5b0c82abb1e04862207c98e676563b7d41ddf7e36a1343d447988aefbab4b6ac; review_identity=sha256:0170ef952b2eaed01cf6ed257965f3efcd27af0800a2c251b39f60929b9df634; result_identity=sha256:cd528df14996640057922edaa8e79131155f620462bc9780018048a132c79e98`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: GETUG-AFU-15 main_article.pdf, pp. 1, 2, 3, 5

- **Progression-Free Survival / LATITUDE**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=b81c430d15cc08b9a53fea867c3d5d07b9dcfa133c4114a677814c5c7fe5eab7; review_identity=sha256:fa3e32219b452eea321680ff9f06e9ec41269e43015e7e603464173df151cd70; result_identity=sha256:27612de6d85bac8933b6906a64706824b4c3cd8f74871427ecce6e29961b3f30`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: LATITUDE main_article.pdf, pp. 1, 3, 4, 5

- **Progression-Free Survival / PEACE-1**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `estimate`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.estimate`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=ff60c68ac40b3b2097cd3871c54b2a289018f5d243bea491b471a06f58ebe033; review_identity=sha256:786d7c324d7cd46c2878f5b256b5d84870e367f493c38e08045cfffbdbebba22; result_identity=sha256:232464e560cd7d1d3b3bfd53bd1d222295fe9dfa7d26153ab9a278d0e063c133`
  - Decision: `equivalent`
  - Rationale: The replacement proposal identifies PEACE-1 radiographic progression-free survival in the overall randomized population and retains the prompted PCWG2 definition in its target measurement. The reported endpoint wording is shorter than the supplied definition, and the comparison arm labels describe the same pooled abiraterone allocation across radiotherapy strata. The adjusted HR and 99.9% confidence interval match the source-reported overall-population result; the one consent withdrawal is disclosed. These wording and analysis-population details do not identify a different result.
  - Source locator: PEACE-1 main_article.pdf, pp. 3, 4, 5, 6

- **Progression-Free Survival / STAMPEDE**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`
  - Adjudication identity: `expected_result_sha256=e5fd5ce4158b29270cf39dfda02d3b11421fb2177380e07adc38266efbc9278c; review_identity=sha256:618d2211ff3dabb9fb40c86307ac2846d180bb4d87650b0b6ec81a6b6f851398; result_identity=sha256:3c85479aab65443812fb13ae26ab2f03273c19f11d8c13c8aa96c639fe48e80c`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: STAMPEDE main_article.pdf, pp. 2, 3, 4, 6

- **Progression-Free Survival / SWOG-1216**
  - Proposal relation: `narrower`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.effect_measure`, `reported_scope.endpoint.definition`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=0321301459f5dcbe58dc3b6b295dc0782a9074aa862ee79632b9ad2cc9d1679b; review_identity=sha256:f6ba48d0f5a1813765e08d04957ab7c65ee824b1068bb001e9decf441c5b311d; result_identity=sha256:7e8004b1cd1611ee546e0f2ba494b933c7944d1b7593a9e79d98c74231bafd74`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: SWOG-1216 main_article.pdf, pp. 1, 2, 3, 4

- **Progression-Free Survival / TITAN**
  - Proposal relation: `exact`
  - Result status: `adjudicated_equivalent`
  - Differing facets: `comparison[0].assignment`, `comparison[0].id`, `comparison[1].assignment`, `comparison[1].id`, `endpoint_definition`, `population`, `window_or_cutoff.description`, `precision`, `reported_scope.analysis_population`, `reported_scope.endpoint.definition`, `reported_scope.endpoint.name`, `reported_scope.precision`
  - Adjudication identity: `expected_result_sha256=b05bca3cdc8741c7b49e12c8b017a24949a71e997cf1101bc4ca1977057b4073; review_identity=sha256:d6d7ee4b0016595ef7840a627c60bf04db2301c092db374a74e1f2b7b2dee3e5; result_identity=sha256:2b6b2f815db48aaf77f7a97c3a22a14db1ad79b58d529c9ad9b96d7eb6ac4328`
  - Decision: `equivalent`
  - Rationale: The proposal selects the same trial endpoint/result and point estimate supplied in the prompt. Arm identifiers, table formatting, confidence-interval punctuation, and source-reported analysis-set wording differ from the frozen metadata but do not identify a different result; any narrower analysis set remains disclosed in the proposal relation rationale for RoB assessment.
  - Source locator: TITAN main_article.pdf, pp. 1, 3, 5, 9


## Pooled result

| Measure | Exact | Low vs Non-Low |
|---|---:|---:|
| Five domains (125 cells) | 80/125 (64.0%) | 93/125 (74.4%) |
| Overall final label (25 cases) | 2/25 (8.0%) | 20/25 (80.0%) |

## Scope-difference sensitivity

The primary results include exact scope matches and source-adjudicated `equivalent` cases. This sensitivity aggregate adds cases adjudicated `accepted_with_scope_difference` (broader or related).
- Added scope-difference cases: 0.

| Measure | Exact | Low vs Non-Low |
|---|---:|---:|
| Five domains (125 cells) | 80/125 (64.0%) | 93/125 (74.4%) |
| Overall final label (25 cases) | 2/25 (8.0%) | 20/25 (80.0%) |

## Accuracy by outcome

| Outcome | Cases | Domains exact | Domains Low vs Non-Low | Overall exact | Overall Low vs Non-Low |
|---|---:|---:|---:|---:|---:|
| Overall Survival | 10 | 37/50 (74.0%) | 40/50 (80.0%) | 2/10 (20.0%) | 7/10 (70.0%) |
| Progression-Free Survival | 9 | 26/45 (57.8%) | 32/45 (71.1%) | 0/9 (0.0%) | 8/9 (88.9%) |
| Adverse Events | 6 | 17/30 (56.7%) | 21/30 (70.0%) | 0/6 (0.0%) | 5/6 (83.3%) |

## Accuracy by domain

| Domain | Exact | Low vs Non-Low |
|---|---:|---:|
| D1 | 25/25 (100.0%) | 25/25 (100.0%) |
| D2 | 14/25 (56.0%) | 14/25 (56.0%) |
| D3 | 11/25 (44.0%) | 18/25 (72.0%) |
| D4 | 18/25 (72.0%) | 24/25 (96.0%) |
| D5 | 12/25 (48.0%) | 12/25 (48.0%) |

## Accuracy by outcome and domain

Exact agreement:

| Outcome | D1 | D2 | D3 | D4 | D5 |
|---|---:|---:|---:|---:|---:|
| Overall Survival | 10/10 (100.0%) | 6/10 (60.0%) | 5/10 (50.0%) | 10/10 (100.0%) | 6/10 (60.0%) |
| Progression-Free Survival | 9/9 (100.0%) | 6/9 (66.7%) | 4/9 (44.4%) | 5/9 (55.6%) | 2/9 (22.2%) |
| Adverse Events | 6/6 (100.0%) | 2/6 (33.3%) | 2/6 (33.3%) | 3/6 (50.0%) | 4/6 (66.7%) |

Low vs Non-Low agreement:

| Outcome | D1 | D2 | D3 | D4 | D5 |
|---|---:|---:|---:|---:|---:|
| Overall Survival | 10/10 (100.0%) | 6/10 (60.0%) | 8/10 (80.0%) | 10/10 (100.0%) | 6/10 (60.0%) |
| Progression-Free Survival | 9/9 (100.0%) | 6/9 (66.7%) | 7/9 (77.8%) | 8/9 (88.9%) | 2/9 (22.2%) |
| Adverse Events | 6/6 (100.0%) | 2/6 (33.3%) | 3/6 (50.0%) | 6/6 (100.0%) | 4/6 (66.7%) |

## Accuracy by primary or secondary outcome

Co-primary and other explicitly primary endpoints are in the Primary row.

| Outcome role | Cases | Domains exact | Domains Low vs Non-Low | Overall exact | Overall Low vs Non-Low |
|---|---:|---:|---:|---:|---:|
| Primary | 13 | 46/65 (70.8%) | 51/65 (78.5%) | 2/13 (15.4%) | 9/13 (69.2%) |
| Secondary | 12 | 34/60 (56.7%) | 42/60 (70.0%) | 0/12 (0.0%) | 11/12 (91.7%) |

## Excluded cases

| Outcome | Trial | Reason |
|---|---|---|
| Adverse Events | ARASENS | The approved safety Result uses treatment-received group membership, including a participant assigned to placebo who received darolutamide. The existing generic equivalence rationale does not address this grouping facet; obtain a separate source-grounded decision before including this case in the primary score. |

The machine-readable scorer output contains complete case-level expected and observed labels. The benchmark manifest records each trial-specific definition, abstract effect estimate, role, prompt, and run directory.

A sanitized [case-level machine summary](2026-09-27-result-scope-score.json) is published beside this report. Rebuild both with `python scripts/score_fresh_scope_review.py`.
