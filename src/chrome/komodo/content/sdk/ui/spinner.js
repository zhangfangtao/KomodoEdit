/**
 * @copyright (c) 2016 ActiveState Software Inc.
 * @license Mozilla Public License v. 2.0
 * @author NathanR, CareyH
 */

var parent = require("./container");
var Module = Object.assign({}, parent);
module.exports = Module;

(function() {
    
    this.Model = Object.assign({}, this.Model);
    
    (function() {
        
        this.name = "hbox";
        this.attributes = { class: "ui-spinner enabled" };
        
        this.init = function()
        {
            this.defaultInit.apply(this, arguments);
            
            this.addElement(require("ko/ui/container").create({ class: "rect1" }));
            this.addElement(require("ko/ui/container").create({ class: "rect2" }));
            this.addElement(require("ko/ui/container").create({ class: "rect3" }));
        };
        
        this.hide = function ()
        {
            this.$element.hide.apply(this.$element, arguments);
            this.$element.removeClass("enabled");
        };

        this.show = function ()
        {
            this.$element.hide.apply(this.$element, arguments);
            this.$element.addClass("enabled");
        };
        
    }).apply(this.Model);
    
}).apply(Module);
