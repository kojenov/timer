<!DOCTYPE html>
<html>

<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TIMER</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bulma@0.8.2/css/bulma.min.css">
  <style>
    .columns {
      margin-top: -0.5rem !important;
      margin-bottom: -0.5rem !important;
      margin-left: 0 !important;
      margin-right: 0 !important;
    }
    .column {
      padding-left: 0.25rem !important;
      padding-right: 0.25rem !important;
    }
    .box {
      margin-bottom: 0.3rem !important;
      padding: 0.5rem !important;
    }
    .timer-padding {
      padding: 0.5rem !important;
    }
  </style>
</head>

<body onload="hideAdvanced()">

  <script>
    function hideAdvanced() {
      var elements = document.getElementsByName("advanced");
      for (var i = 0; i < elements.length; i++) {
        elements[i].classList.add("is-hidden");
      }
    }

    function toggleAdvanced() {
      var simple = false;
      var elements = document.getElementsByName("advanced");
      for (var i = 0; i < elements.length; i++) {
        if (elements[i].classList.contains("is-hidden")) {
          elements[i].classList.remove("is-hidden");
          simple = true;
        } else {
          elements[i].classList.add("is-hidden");
        }
      }
      if (simple) {
        document.getElementById("advButton").textContent="simple";
      } else {
        document.getElementById("advButton").textContent="advanced";
      }
    }

    function toggleTemp() {
      var button = document.getElementById("tempButton");
      if (button.textContent == "temp access") {
        hide = "schedBlock";
        show = "tempBlock";
        button.textContent = "shedule";
      } else {
        hide = "tempBlock";
        show = "schedBlock";
        button.textContent = "temp access";
      }
      var elements = document.getElementsByName(hide);
      for (var i = 0; i < elements.length; i++) {
        elements[i].classList.add("is-hidden");
      }
      var elements = document.getElementsByName(show);
      for (var i = 0; i < elements.length; i++) {
        elements[i].classList.remove("is-hidden");
      }
    }

  </script>

  %try:
    %if errors != None and not errors:
      <article class="message is-success">
        <div class="message-body">The configuration was saved successfully!</div>
      </article>
    %end
  %except NameError:
    
  %end

  %if errors:
    <article class="message is-danger">
      <div class="message-body">
        %for error in errors:
          {{ error }}<br/>
        %end
      </div>
    </article>
  %end

  <div class="box has-text-centered">
    <button id="tempButton" class="button is-info is-light" onclick="toggleTemp()">temp access</button>
    <button id="advButton" class="button is-info is-light" onclick="toggleAdvanced()">advanced</button>
  </div>
  
  <form method="POST">
  
    <input type="hidden" name="oldState" value="{{ oldState }}" readonly>

    %for mac,client in state:

      %advanced = 'advanced' if client['sched'] == '*' or (not client['name'] and not client['sched']) else ''
      
      %new = 'has-background-light' if client['new'] else ''
      
      <div name="{{ advanced }}" class="box {{ new }}">
        <div class="columns is-mobile is-vcentered">
          <div class="column">
            <input class="input is-success" type="text" name="name" value="{{ client['name'] }}" placeholder="name">
          </div>
          
          <div class="column is-two-fifths" name="schedBlock">
            <input class="input is-danger" type="text" name="sched" value="{{ client['sched'] }}" placeholder="schedule">
          </div>  
          
          <div class="column is-one-third is-hidden" name="tempBlock">
            <div class="select is-danger">
              <select name="temp">
                %for opt in [['',''], ['15',':15'], ['30',':30'], ['45',':45'], ['60','1'], ['90','1.5'], ['120','2'], ['240','4'], ['480', '8'], ['1440','24']]:
                  %if client['temp'] == opt[0]:
                    %selected = 'selected'
                  %else:
                    %selected = ''
                  %end
                  <option value="{{ opt[0] }}" {{ selected }}>{{ opt[1] }}</option>
                %end
              </select>
            </div>
          </div>  

        </div>
          
        <div class="has-text-info timer-padding" name="advanced">
          <em>{{ mac }} &nbsp; {{ client['ip'] }}</em>
          %if not client['ip']:
            %checked = 'checked' if client['forget'] else ''
            <input type="checkbox" name="forget" value="{{ mac }}" {{ checked }}> forget</input>
          %end
        </div>

        <input type="hidden" name="mac" value="{{ mac }}"  readonly>

      </div>

    %end
  
    <div class="box has-text-centered">
      <input class="button is-link" type="submit" value="save">
    </div>
  
  </form>

  </table>

</body>

</html>
