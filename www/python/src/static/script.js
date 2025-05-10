/* static/script.js
   ---------------------------------------------------------------------------
   Shared front-end logic for the Mix-n-Match “Birdmaps” explorer
   --------------------------------------------------------------------------- */

(function () {
    /* ─────────────────────────────────────────────────────────────────────────
       1. AUTOCOMPLETE ON / (index.html)
       ───────────────────────────────────────────────────────────────────────── */

    const $city = $('#city');               // present only on the search page
    if ($city.length) {
        $city.autocomplete({
            // We can use simple JSON now: the Wikidata API supports CORS with origin=*
            serviceUrl: 'https://www.wikidata.org/w/api.php',
            dataType: 'json',
            paramName: 'search',
            params: {
                action: 'wbsearchentities',
                format: 'json',
                language: 'en',
                uselang: 'en',
                type: 'item',
                origin: '*',          // <── enables CORS
            },
            transformResult: function (response) {
                const filtered = (response.search || []).filter(
                    (item) => item.match && item.match.type === 'label'
                );
                return {
                    suggestions: $.map(filtered, function (item) {
                        const desc = item.description ? ` (${item.description})` : '';
                        return {
                            value: item.label + desc,
                            data: { id: item.id },
                        };
                    }),
                };
            },
            onSelect: function (suggestion) {
                $.ajax({
                    url: 'https://www.wikidata.org/w/api.php',
                    dataType: 'json',
                    data: {
                        action: 'wbgetentities',
                        ids: suggestion.data.id,
                        props: 'claims',
                        format: 'json',
                        origin: '*',
                    },
                    success: function (data) {
                        const entity = data.entities[suggestion.data.id];
                        const coords = entity?.claims?.P625;
                        const value = coords?.[0]?.mainsnak?.datavalue?.value;
                        if (value) {
                            $('#lat').val(value.latitude);
                            $('#lng').val(value.longitude);
                        } else {
                            alert('Selected entry has no coordinates.');
                        }
                    },
                });
            },
        });

        /* tiny helper so the user can’t submit without coords */
        window.validateCoordinates = function () {
            const lat = $('#lat').val();
            const lng = $('#lng').val();
            if (!lat || !lng) {
                alert('Please select a valid location from the autocomplete list.');
                return false;
            }
            return true;
        };
    }

    /* ─────────────────────────────────────────────────────────────────────────
       2. LEAFLET MAP ON /map  (map.html)
       ───────────────────────────────────────────────────────────────────────── */

    const mapContainer = document.getElementById('mapid');
    if (mapContainer && window.mapData) {
        // initLat / initLng are embedded by Jinja in the template
        const map = L.map('mapid').setView([window.initLat, window.initLng], 11);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution:
                '© OpenStreetMap contributors | Places © iNaturalist / Wikidata',
        }).addTo(map);

        /* simple coloured icons (pointhi/leaflet-color-markers) */
        const blueIcon = new L.Icon({
            iconUrl:
                'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-blue.png',
            shadowUrl:
                'https://unpkg.com/leaflet@1.7.1/dist/images/marker-shadow.png',
            iconSize: [25, 41],
            iconAnchor: [12, 41],
            popupAnchor: [1, -34],
            shadowSize: [41, 41],
        });
        const redIcon = new L.Icon({
            iconUrl:
                'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png',
            shadowUrl:
                'https://unpkg.com/leaflet@1.7.1/dist/images/marker-shadow.png',
            iconSize: [25, 41],
            iconAnchor: [12, 41],
            popupAnchor: [1, -34],
            shadowSize: [41, 41],
        });

        const markers = L.featureGroup().addTo(map);

        window.mapData.forEach((h) => {
            const icon = h.wikidata ? blueIcon : redIcon;
            const m = L.marker([h.lat, h.lng], { icon }).addTo(markers);

            /* popup: name, clickable link when there’s a Q-id, optional image */
            let popupHTML = `<strong>${h.locName}</strong>`;
            if (h.wikidata) {
                popupHTML += `<br><a href="${h.wikidata}" target="_blank">View on Wikidata</a>`;
            }
            if (h.image) {
                popupHTML += `<br><img src="${h.image}" alt="" style="max-width:150px;max-height:150px;margin-top:4px;">`;
            }
            m.bindPopup(popupHTML);
        });

        // Fit map bounds to all markers (fallback to centre if only one point)
        if (markers.getLayers().length > 0) {
            map.fitBounds(markers.getBounds().pad(0.2));
        }
    }
})();
